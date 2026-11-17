"""GameInstance 模型测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from models.game_instance import GameInstance, InstanceStatus


def test_create_instance_has_independent_identity(tmp_path) -> None:
    """每个实例都有自己的标识，路径会被保存为绝对路径。"""
    exe = tmp_path / "game.exe"
    first = GameInstance.create("账号实例01", str(exe), ["-windowed"])
    second = GameInstance.create("账号实例02", str(exe))
    assert first.instance_id != second.instance_id
    assert first.status == InstanceStatus.STOPPED
    assert first.startup_arguments == ["-windowed"]
    assert first.exe_path == str(exe.resolve())
    assert first.pid is None
    assert first.status_label == "已停止"


def test_status_labels() -> None:
    """状态中文名与需求一致。"""
    assert InstanceStatus.STOPPED.label == "已停止"
    assert InstanceStatus.STARTING.label == "启动中"
    assert InstanceStatus.RUNNING.label == "运行中"
    assert InstanceStatus.STOPPING.label == "关闭中"
    assert InstanceStatus.ERROR.label == "异常"


def test_reject_empty_name() -> None:
    """空名称不能构成可管理的实例。"""
    with pytest.raises(ValueError):
        GameInstance.create("  ", "/tmp/game.exe")


def test_roundtrip_dict() -> None:
    """字典往返后保留进程身份和启动参数。"""
    start_time = datetime(2026, 11, 17, 12, 0, 0)
    instance = GameInstance.create("账号实例01", "/tmp/game.exe", ["-user", "hero"])
    instance.pid = 1234
    instance.process_create_time = 1000.5
    instance.status = InstanceStatus.RUNNING
    instance.start_time = start_time
    instance.last_error = None

    restored = GameInstance.from_dict(instance.to_dict())
    assert restored.instance_id == instance.instance_id
    assert restored.startup_arguments == ["-user", "hero"]
    assert restored.pid == 1234
    assert restored.process_create_time == 1000.5
    assert restored.status == InstanceStatus.RUNNING
    assert restored.start_time == start_time


def test_runtime_seconds_only_while_running() -> None:
    """已停止的实例不计算运行时间。"""
    instance = GameInstance.create("账号实例01", "/tmp/game.exe")
    assert instance.runtime_seconds() is None
    instance.status = InstanceStatus.RUNNING
    instance.start_time = datetime.now() - timedelta(seconds=10)
    assert instance.runtime_seconds() >= 9
