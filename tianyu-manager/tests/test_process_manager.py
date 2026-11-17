"""ProcessManager 测试。

全部使用 Python 模拟进程，不启动真实游戏客户端。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import psutil
import pytest

from core.process_manager import (
    ProcessIdentity,
    ProcessManager,
    choose_graceful_action,
    normalize_startup_arguments,
    request_graceful_close,
)
from models.game_instance import GameInstance, InstanceStatus
from utils.logger import log_file_path

SLEEPER = Path(__file__).resolve().parent / "fixtures" / "sleeper.py"
SOURCE = Path(__file__).resolve().parents[1] / "core" / "process_manager.py"


def make_instance(
    name: str,
    mode: str = "exit-on-term",
    seconds: float = 60,
    token: str | None = None,
) -> GameInstance:
    """用当前 Python 解释器和模拟脚本构造一个实例。"""
    marker = token or uuid4().hex
    return GameInstance.create(
        name,
        sys.executable,
        [str(SLEEPER), "--mode", mode, "--seconds", str(seconds), "--token", marker],
    )


def processes_with_token(token: str) -> list[int]:
    """找出命令行中带有指定标记的模拟进程。"""
    found: list[int] = []
    for process in psutil.process_iter(["pid", "cmdline"]):
        cmdline = process.info.get("cmdline") or []
        if token in cmdline:
            found.append(process.info["pid"])
    return found


def test_normalize_arguments_does_not_invent_flags() -> None:
    """只保留用户输入，不追加预设参数。"""
    assert normalize_startup_arguments(None) == []
    assert normalize_startup_arguments("  ") == []
    assert normalize_startup_arguments(["-windowed"]) == ["-windowed"]
    assert normalize_startup_arguments('-user "hero one"') == ["-user", "hero one"]


def test_graceful_action_never_targets_image_name() -> None:
    """关闭策略只区分窗口和信号，不包含按文件名结束。"""
    assert choose_graceful_action("win32", 2) == "wm_close"
    assert choose_graceful_action("win32", 0) == "ctrl_break"
    assert choose_graceful_action("darwin", 0) == "sigterm"
    source = SOURCE.read_text(encoding="utf-8").lower()
    # 模块说明里会写明禁止 taskkill；实现代码不能真正调用它，也不能按进程名枚举。
    _doc, _, body = source.partition('"""')
    _doc, _, body = body.partition('"""')
    del _doc
    assert "taskkill" not in body
    assert "process_iter" not in body


def test_windows_close_does_not_kill_when_window_exists() -> None:
    """已经投递 WM_CLOSE 时，不再发送终止信号。"""
    calls: list[tuple[int, int]] = []
    method = request_graceful_close(
        50,
        platform="win32",
        window_count=2,
        killer=lambda pid, sig: calls.append((pid, sig)),
    )
    assert method == "wm_close:2"
    assert calls == []


def test_windows_without_window_uses_console_break_for_that_pid() -> None:
    """没有窗口时，只向该 PID 发送控制台中断信号。"""
    calls: list[tuple[int, int]] = []
    method = request_graceful_close(
        50,
        platform="win32",
        window_count=0,
        console_signal=21,
        killer=lambda pid, sig: calls.append((pid, sig)),
    )
    assert method == "ctrl_break"
    assert calls == [(50, 21)]


def test_missing_executable_is_recorded(process_manager: ProcessManager) -> None:
    """文件不存在时不创建进程，并记下错误。"""
    instance = GameInstance.create("账号实例01", "/tmp/tianyu-missing-game.exe")
    result = process_manager.start(instance)
    assert result.success is False
    assert instance.status == InstanceStatus.ERROR
    assert instance.pid is None
    assert instance.last_error is not None
    assert "不存在" in instance.last_error
    assert process_manager.managed_instances() == []


def test_start_records_pid_and_create_time(process_manager: ProcessManager) -> None:
    """启动成功后保存的 PID 和创建时间必须属于同一个进程。"""
    instance = make_instance("账号实例01")
    result = process_manager.start(instance)
    assert result.success is True
    assert result.pid == instance.pid
    assert instance.status == InstanceStatus.RUNNING
    assert instance.process_create_time is not None
    process = psutil.Process(instance.pid)
    assert abs(process.create_time() - instance.process_create_time) < 1.0
    assert process_manager.is_running(instance)


def test_duplicate_start_does_not_create_second_process(process_manager: ProcessManager) -> None:
    """同一实例正在运行时，第二次启动必须失败且不能再拉起进程。"""
    token = uuid4().hex
    instance = make_instance("账号实例01", token=token)
    assert process_manager.start(instance).success is True
    second = process_manager.start(instance)
    assert second.success is False
    assert "重复启动" in second.message
    assert processes_with_token(token) == [instance.pid]


def test_quick_exit_reports_multi_instance_limit(process_manager: ProcessManager) -> None:
    """进程立刻退出时标记异常，并提示不要绕过多开限制。"""
    instance = make_instance("账号实例01", mode="exit-immediately")
    result = process_manager.start(instance)
    assert result.success is False
    assert instance.status == InstanceStatus.ERROR
    assert instance.pid is None
    assert instance.last_error is not None
    assert "多开" in instance.last_error
    assert process_manager.is_running(instance) is False


def test_start_five_instances_and_shutdown_one(process_manager: ProcessManager) -> None:
    """五个实例拥有各自的 PID，关闭其中一个不影响其余实例。"""
    instances = [make_instance(f"账号实例{index:02d}") for index in range(1, 6)]
    results = process_manager.start_many(instances, interval_seconds=0)
    assert [item.success for item in results] == [True, True, True, True, True]
    pids = [instance.pid for instance in instances]
    assert len(set(pids)) == 5

    shutdown = process_manager.shutdown(instances[0], timeout=3)
    assert shutdown.success is True
    assert instances[0].status == InstanceStatus.STOPPED
    assert instances[0].pid is None
    for instance in instances[1:]:
        assert process_manager.is_running(instance)

    all_results = process_manager.shutdown_all(timeout=3)
    assert len(all_results) == 4
    assert all(item.success for item in all_results)
    assert all(instance.status == InstanceStatus.STOPPED for instance in instances)


def test_batch_start_skips_running_and_continues_after_failure(
    process_manager: ProcessManager,
) -> None:
    """批量启动逐个检查：已运行的跳过，失败的实例不阻断后续实例。"""
    running = make_instance("账号实例01")
    missing = GameInstance.create("账号实例02", "/tmp/tianyu-missing-game.exe")
    waiting = make_instance("账号实例03")
    assert process_manager.start(running).success is True

    results = process_manager.start_many([running, missing, waiting], interval_seconds=0)
    assert results[0].success is False
    assert results[1].success is False
    assert results[2].success is True
    assert process_manager.is_running(running)
    assert process_manager.is_running(waiting)
    assert missing.status == InstanceStatus.ERROR


def test_batch_interval_is_applied(process_manager: ProcessManager) -> None:
    """批量启动会在两个实例之间等待指定间隔。"""
    instances = [make_instance("账号实例01"), make_instance("账号实例02")]
    started = time.monotonic()
    results = process_manager.start_many(instances, interval_seconds=0.4)
    elapsed = time.monotonic() - started
    assert all(item.success for item in results)
    assert elapsed >= 0.4


def test_shutdown_does_not_kill_process_started_elsewhere(process_manager: ProcessManager) -> None:
    """未由本程序启动的进程，即使 PID 被写进实例，也不能被关闭。"""
    external = subprocess.Popen(
        [sys.executable, str(SLEEPER), "--mode", "exit-on-term", "--seconds", "60"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        foreign = GameInstance.create("外部客户端", sys.executable)
        foreign.pid = external.pid
        foreign.process_create_time = psutil.Process(external.pid).create_time()
        result = process_manager.shutdown(foreign, timeout=0.3)
        assert result.success is False
        assert result.identity_mismatch is True
        assert external.poll() is None
    finally:
        external.kill()
        external.wait(timeout=3)


def test_shutdown_uses_recorded_identity_when_instance_pid_is_overwritten(
    process_manager: ProcessManager,
) -> None:
    """实例上的 PID 被改成其他进程后，关闭的仍是原进程。"""
    external = subprocess.Popen(
        [sys.executable, str(SLEEPER), "--mode", "exit-on-term", "--seconds", "60"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        instance = make_instance("账号实例01")
        assert process_manager.start(instance).success is True
        original_pid = instance.pid
        assert original_pid is not None
        original_create_time = instance.process_create_time
        instance.pid = external.pid
        instance.process_create_time = psutil.Process(external.pid).create_time()

        result = process_manager.shutdown(instance, timeout=3)
        assert result.success is True
        assert external.poll() is None
        assert _process_gone(original_pid, original_create_time)
    finally:
        if external.poll() is None:
            external.kill()
            external.wait(timeout=3)


def test_mismatched_create_time_refuses_to_kill(process_manager: ProcessManager) -> None:
    """创建时间对不上时，正常关闭和强制结束都不得终止该 PID。"""
    instance = make_instance("账号实例01")
    assert process_manager.start(instance).success is True
    pid = instance.pid
    assert pid is not None
    original_inspect = process_manager._inspect

    def fake_inspect(checked_pid: int, create_time: float) -> ProcessIdentity:
        if checked_pid == pid:
            return ProcessIdentity.MISMATCH
        return original_inspect(checked_pid, create_time)

    process_manager._inspect = fake_inspect  # type: ignore[method-assign]
    try:
        shutdown = process_manager.shutdown(instance, timeout=0.2)
        forced = process_manager.force_terminate(instance)
        assert shutdown.identity_mismatch is True
        assert forced.identity_mismatch is True
        assert psutil.Process(pid).is_running()
    finally:
        process_manager._inspect = original_inspect  # type: ignore[method-assign]


def test_timeout_does_not_force_kill(process_manager: ProcessManager) -> None:
    """进程忽略正常退出请求时，等待超时后必须保持运行。"""
    instance = make_instance("账号实例01", mode="ignore-term")
    assert process_manager.start(instance).success is True
    result = process_manager.shutdown(instance, timeout=0.4)
    assert result.success is False
    assert result.timed_out is True
    assert result.needs_user_decision is True
    assert instance.status == InstanceStatus.RUNNING
    pid = instance.pid
    create_time = instance.process_create_time
    assert pid is not None
    assert psutil.Process(pid).is_running()

    forced = process_manager.force_terminate(instance)
    assert forced.success is True
    assert instance.status == InstanceStatus.STOPPED
    assert _process_gone(pid, create_time)


def test_attach_requires_both_pid_and_create_time(process_manager: ProcessManager) -> None:
    """接管必须同时匹配 PID 和创建时间，匹配失败时进程继续运行。"""
    external = subprocess.Popen(
        [sys.executable, str(SLEEPER), "--mode", "exit-on-term", "--seconds", "60"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    other = subprocess.Popen(
        [sys.executable, str(SLEEPER), "--mode", "exit-on-term", "--seconds", "60"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        wrong = GameInstance.create("错误身份", sys.executable)
        wrong.pid = external.pid
        wrong.process_create_time = 1.0
        assert process_manager.attach_persisted(wrong) is False
        assert external.poll() is None

        owned = GameInstance.create("已保存实例", sys.executable)
        owned.pid = external.pid
        owned.process_create_time = psutil.Process(external.pid).create_time()
        assert process_manager.attach_persisted(owned) is True
        result = process_manager.shutdown(owned, timeout=3)
        assert result.success is True
        assert other.poll() is None
    finally:
        for process in (external, other):
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)


def test_logs_contain_start_and_shutdown(process_manager: ProcessManager, tmp_path: Path) -> None:
    """启动和关闭会写入当天的日志文件。"""
    instance = make_instance("账号实例01")
    assert process_manager.start(instance).success is True
    assert process_manager.shutdown(instance, timeout=3).success is True
    log_path = log_file_path(tmp_path / "logs")
    content = log_path.read_text(encoding="utf-8")
    assert "启动游戏" in content
    assert "关闭游戏" in content
    assert "状态变化" in content


def test_negative_interval_is_rejected(process_manager: ProcessManager) -> None:
    """非法间隔直接拒绝，不启动进程。"""
    with pytest.raises(ValueError):
        process_manager.start_many([make_instance("账号实例01")], interval_seconds=-1)


def _process_gone(pid: int | None, create_time: float | None) -> bool:
    """判断原进程是否已退出。PID 被复用且创建时间不同也视为原进程已消失。"""
    if pid is None:
        return True
    try:
        process = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return True
    if create_time is None:
        return not process.is_running()
    return abs(process.create_time() - create_time) > 1.0
