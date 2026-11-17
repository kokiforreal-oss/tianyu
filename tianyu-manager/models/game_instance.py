"""游戏实例数据模型。

每个实例单独保存进程身份。判断某个客户端是否属于该实例时，
必须同时核对 PID 和进程创建时间，不能只比较可执行文件名。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


class InstanceStatus(str, Enum):
    """实例生命周期状态。"""

    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"

    @property
    def label(self) -> str:
        """返回界面使用的中文状态名。"""
        labels = {
            InstanceStatus.STOPPED: "已停止",
            InstanceStatus.STARTING: "启动中",
            InstanceStatus.RUNNING: "运行中",
            InstanceStatus.STOPPING: "关闭中",
            InstanceStatus.ERROR: "异常",
        }
        return labels[self]


@dataclass(slots=True)
class GameInstance:
    """一个可独立启动和关闭的游戏实例。

    属性:
        instance_id: 实例唯一标识，创建后保持不变。
        instance_name: 用户可见的实例名称。
        exe_path: 游戏可执行文件的绝对路径。
        startup_arguments: 用户设置的启动参数。程序不会自动追加未知参数。
        pid: 最近一次由本程序启动后记录的进程 ID。停止后清空。
        process_create_time: 进程创建时间（秒级时间戳）。与 PID 一起用于防止 PID 复用后误识别。
        status: 当前生命周期状态。
        start_time: 最近一次成功进入运行状态的本地时间。
        last_error: 最近一次错误说明。没有错误时为 None。
    """

    instance_id: str
    instance_name: str
    exe_path: str
    startup_arguments: list[str] = field(default_factory=list)
    pid: int | None = None
    process_create_time: float | None = None
    status: InstanceStatus = InstanceStatus.STOPPED
    start_time: datetime | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        """校验标识、名称和状态，避免写入无法管理的实例。"""
        if not self.instance_id or not str(self.instance_id).strip():
            raise ValueError("instance_id 不能为空")
        if not self.instance_name or not self.instance_name.strip():
            raise ValueError("实例名称不能为空")
        self.instance_id = str(self.instance_id)
        self.instance_name = self.instance_name.strip()
        self.status = InstanceStatus(self.status)
        self.startup_arguments = [str(item) for item in self.startup_arguments]

    @staticmethod
    def create(
        instance_name: str,
        exe_path: str,
        startup_arguments: list[str] | None = None,
        instance_id: str | None = None,
    ) -> GameInstance:
        """创建一个尚未启动的实例。

        创建时不要求可执行文件已经存在，方便用户先保存配置再修改路径。
        真正启动前仍会检查文件。

        参数:
            instance_name: 实例名称。
            exe_path: 游戏 EXE 路径，相对路径会转换为绝对路径。
            startup_arguments: 启动参数列表。不传则保持为空。
            instance_id: 指定标识时用于从持久化数据恢复；否则自动生成。
        """
        path_text = exe_path.strip()
        if path_text:
            # 统一保存绝对路径，避免工作目录变化后找不到游戏。
            path_text = str(Path(path_text).expanduser().resolve())
        return GameInstance(
            instance_id=instance_id or str(uuid4()),
            instance_name=instance_name,
            exe_path=path_text,
            startup_arguments=list(startup_arguments or []),
        )

    @property
    def status_label(self) -> str:
        """当前状态的中文名称。"""
        return self.status.label

    def runtime_seconds(self, now: datetime | None = None) -> float | None:
        """返回本次运行已持续的秒数。

        只有状态为运行中且存在启动时间时才计算，避免把已停止实例显示成仍在计时。
        """
        if self.status != InstanceStatus.RUNNING or self.start_time is None:
            return None
        current = now or datetime.now()
        return max(0.0, (current - self.start_time).total_seconds())

    def to_dict(self) -> dict[str, Any]:
        """转换为可写入数据库或配置文件的普通字典。"""
        return {
            "instance_id": self.instance_id,
            "instance_name": self.instance_name,
            "exe_path": self.exe_path,
            "startup_arguments": list(self.startup_arguments),
            "pid": self.pid,
            "process_create_time": self.process_create_time,
            "status": self.status.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameInstance:
        """从字典恢复实例。

        参数:
            data: `to_dict` 产生的字典，或数据库读出的同等结构。

        异常:
            KeyError: 缺少实例标识、名称或路径。
            ValueError: 状态值无法识别。
        """
        start_text = data.get("start_time")
        pid = data.get("pid")
        create_time = data.get("process_create_time")
        return cls(
            instance_id=str(data["instance_id"]),
            instance_name=str(data["instance_name"]),
            exe_path=str(data["exe_path"]),
            startup_arguments=[str(item) for item in data.get("startup_arguments") or []],
            pid=int(pid) if pid is not None else None,
            process_create_time=float(create_time) if create_time is not None else None,
            status=InstanceStatus(data.get("status", InstanceStatus.STOPPED)),
            start_time=datetime.fromisoformat(start_text) if start_text else None,
            last_error=data.get("last_error"),
        )
