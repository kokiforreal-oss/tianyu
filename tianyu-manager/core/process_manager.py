"""游戏进程的启动、身份校验和安全关闭。

安全约束：
- 只管理本对象启动或显式接管的进程。
- 关闭前同时核对 PID 和进程创建时间，避免 PID 被系统复用后误杀。
- 默认只发送正常退出请求，超时后交给调用方决定，不强制结束。
- 不按可执行文件名批量结束进程，也不调用 taskkill /IM。
"""

from __future__ import annotations

import logging
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

import psutil

from models.game_instance import GameInstance, InstanceStatus
from utils.logger import attach_daily_file_logger

# 进程创建时间允许的比对误差（秒）。同一进程重复读取时，Windows 上可能有轻微舍入差异。
DEFAULT_CREATE_TIME_TOLERANCE = 1.0
DEFAULT_QUICK_EXIT_WINDOW = 1.0
DEFAULT_SHUTDOWN_TIMEOUT = 10.0

_LOGGER_NAME = "tianyu.process"


class ProcessIdentity(Enum):
    """PID 与进程创建时间的核对结果。"""

    MATCH = "match"
    EXITED = "exited"
    MISMATCH = "mismatch"
    INACCESSIBLE = "inaccessible"


@dataclass(slots=True)
class StartResult:
    """一次启动尝试的结果。"""

    instance_id: str
    success: bool
    message: str
    pid: int | None = None


@dataclass(slots=True)
class ShutdownResult:
    """一次关闭尝试的结果。"""

    instance_id: str
    success: bool
    message: str
    timed_out: bool = False
    needs_user_decision: bool = False
    identity_mismatch: bool = False
    method: str = ""


def normalize_startup_arguments(arguments: list[str] | str | None) -> list[str]:
    """把用户输入的启动参数整理成参数列表。

    只解析用户给出的内容，不会补充游戏参数。空字符串得到空列表。

    异常:
        TypeError: 参数不是字符串或字符串列表。
        ValueError: 参数字符串的引号不完整，无法解析。
    """
    if arguments is None:
        return []
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return []
        # 始终按 POSIX 规则去掉引号。Windows 路径里的反斜杠在整段参数字符串中需要写成双反斜杠，
        # 或者直接传入已经拆好的列表。
        return shlex.split(text, posix=True)
    if isinstance(arguments, list):
        normalized: list[str] = []
        for item in arguments:
            if not isinstance(item, str):
                raise TypeError("启动参数必须是字符串")
            normalized.append(item)
        return normalized
    raise TypeError("启动参数必须是字符串或字符串列表")


def choose_graceful_action(platform: str, window_count: int) -> str:
    """选择礼貌关闭方式。

    Windows 有可见或顶层窗口时发送 WM_CLOSE；没有窗口时才向该进程自己的
    进程组发送 CTRL_BREAK。其他系统发送 SIGTERM。两种都不是按名称结束进程。
    """
    if platform == "win32":
        return "wm_close" if window_count > 0 else "ctrl_break"
    return "sigterm"


def post_wm_close(pid: int) -> int:
    """向指定 PID 的顶层窗口投递 WM_CLOSE。

    只比对窗口所属进程 ID，不会按 EXE 名称查找其他客户端。
    非 Windows 平台不执行任何操作并返回 0。

    返回:
        成功投递关闭消息的窗口数量。
    """
    if sys.platform != "win32":
        return 0

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    wm_close = 0x0010
    enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_windows_proc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL

    posted = 0

    def _on_window(hwnd: int, _lparam: int) -> bool:
        nonlocal posted
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == pid and user32.PostMessageW(hwnd, wm_close, 0, 0):
            posted += 1
        return True

    callback = enum_windows_proc(_on_window)
    if not user32.EnumWindows(callback, 0):
        # EnumWindows 在回调要求停止时返回 0。我们的回调始终继续，
        # 返回 0 时更可能是枚举失败，此时不把已投递的次数清零。
        return posted
    return posted


def request_graceful_close(
    pid: int,
    *,
    platform: str | None = None,
    window_count: int | None = None,
    console_signal: int | None = None,
    killer: Callable[[int, int], None] | None = None,
) -> str:
    """向一个已经核对过身份的进程发送正常退出请求。

    此函数不会调用强制结束。Windows 上优先 WM_CLOSE；没有窗口时，
    仅向该 PID 所在的新进程组发送 CTRL_BREAK。

    参数:
        pid: 已通过身份校验的进程 ID。
        platform: 覆盖当前平台，便于在非 Windows 上测试分支。
        window_count: 已知窗口数。不传时在 Windows 上实际枚举窗口。
        console_signal: 测试用的控制台信号值。
        killer: 发送信号的函数，默认是 `os.kill`。

    返回:
        实际采用的方式，例如 `wm_close:1`、`ctrl_break`、`sigterm` 或 `none`。
    """
    current = platform or sys.platform
    send_signal = killer or os.kill
    if current == "win32":
        count = post_wm_close(pid) if window_count is None else window_count
        if choose_graceful_action(current, count) == "wm_close":
            return f"wm_close:{count}"
        sig = console_signal
        if sig is None:
            sig = getattr(signal, "CTRL_BREAK_EVENT", None)
        if sig is None:
            return "none"
        try:
            send_signal(pid, sig)
        except OSError:
            return "none"
        return "ctrl_break"

    try:
        send_signal(pid, signal.SIGTERM)
    except ProcessLookupError:
        return "already_exited"
    return "sigterm"


class ProcessManager:
    """管理本程序启动的游戏进程。

    实例对象本身由调用方持有。这里只保存进程句柄和启动时观察到的身份，
    不使用模块级全局变量共享这些状态。
    """

    def __init__(
        self,
        *,
        quick_exit_window: float = DEFAULT_QUICK_EXIT_WINDOW,
        create_time_tolerance: float = DEFAULT_CREATE_TIME_TOLERANCE,
        log_dir: Path | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """创建进程管理器。

        参数:
            quick_exit_window: 启动后继续观察的秒数。在此时间内退出视为启动失败。
            create_time_tolerance: 进程创建时间的允许误差，单位秒。
            log_dir: 提供时把日志按日期写入该目录。
            logger: 可注入的日志记录器。未提供时使用 `tianyu.process`。

        异常:
            ValueError: 观察窗口或时间误差小于 0。
        """
        if quick_exit_window < 0:
            raise ValueError("quick_exit_window 不能为负数")
        if create_time_tolerance < 0:
            raise ValueError("create_time_tolerance 不能为负数")
        self._quick_exit_window = quick_exit_window
        self._tolerance = create_time_tolerance
        self._lock = threading.RLock()
        self._launching: set[str] = set()
        self._identities: dict[str, tuple[int, float]] = {}
        self._popen: dict[str, subprocess.Popen[bytes]] = {}
        self._instances: dict[str, GameInstance] = {}
        self._logger = logger or logging.getLogger(_LOGGER_NAME)
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = True
        self._handlers: list[logging.Handler] = []
        if log_dir is not None:
            self._handlers.append(attach_daily_file_logger(self._logger, Path(log_dir)))

    def close(self) -> None:
        """关闭本管理器打开的日志文件。不结束任何游戏进程。"""
        for handler in self._handlers:
            self._logger.removeHandler(handler)
            handler.close()
        self._handlers.clear()

    def managed_instances(self) -> list[GameInstance]:
        """返回当前由本管理器跟踪的实例副本列表。"""
        with self._lock:
            return list(self._instances.values())

    def recorded_identity(self, instance_id: str) -> tuple[int, float] | None:
        """返回启动或接管时记录的 PID 和进程创建时间。"""
        with self._lock:
            identity = self._identities.get(instance_id)
            if identity is None:
                return None
            return identity[0], identity[1]

    def is_running(self, instance: GameInstance) -> bool:
        """判断该实例对应的进程是否仍是启动时的同一个进程。"""
        with self._lock:
            return self._is_running_unlocked(instance)

    def start(self, instance: GameInstance) -> StartResult:
        """启动一个实例。

        启动前检查可执行文件是否存在，并拒绝重复启动仍在运行的同一实例。
        成功后把 PID 和进程创建时间写回实例。若进程立刻退出，会标记为异常
        并提示游戏可能不支持多开；本方法不会尝试绕过该限制。

        此方法最多阻塞 `quick_exit_window` 秒，界面线程不应直接调用。
        """
        try:
            arguments = normalize_startup_arguments(instance.startup_arguments)
        except (TypeError, ValueError) as exc:
            return self._fail_start(instance, f"启动参数无效: {exc}")
        instance.startup_arguments = arguments

        with self._lock:
            if instance.instance_id in self._launching or self._is_running_unlocked(instance):
                message = "实例已在运行，禁止重复启动"
                instance.last_error = message
                self._logger.warning("启动失败 [%s] %s", instance.instance_name, message)
                return StartResult(instance.instance_id, False, message, instance.pid)
            self._launching.add(instance.instance_id)
            self._set_status(instance, InstanceStatus.STARTING)

        try:
            return self._spawn(instance)
        except Exception as exc:
            # 只结束本次调用创建的子进程，避免异常路径留下无法再识别的游戏进程。
            self._logger.exception("启动游戏出现未预期错误 [%s]", instance.instance_name)
            with self._lock:
                popen = self._popen.get(instance.instance_id)
            if popen is not None and popen.poll() is None:
                self._kill_unidentified_child(popen)
            return self._fail_start(instance, f"启动失败: {exc}")
        finally:
            with self._lock:
                self._launching.discard(instance.instance_id)

    def start_many(
        self,
        instances: list[GameInstance],
        interval_seconds: float = 0.0,
    ) -> list[StartResult]:
        """按顺序启动多个实例。

        每个实例都会单独检查状态。已经在运行的会被跳过，某个实例失败也不会
        阻止后面的实例。`interval_seconds` 是前一个启动尝试返回后、下一个开始前的间隔。

        异常:
            ValueError: 间隔小于 0。
        """
        if interval_seconds < 0:
            raise ValueError("启动间隔不能为负数")
        results: list[StartResult] = []
        for index, instance in enumerate(instances):
            if index > 0 and interval_seconds > 0:
                time.sleep(interval_seconds)
            results.append(self.start(instance))
        return results

    def shutdown(
        self,
        instance: GameInstance,
        timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> ShutdownResult:
        """请求实例正常退出，并等待它自己结束。

        只关闭本管理器启动或接管的那个 PID。身份对不上时直接拒绝，
        不会改去结束实例对象上被改写过的其他 PID。超时后进程保持运行，
        由调用方提示用户是否进一步处理；本方法不会强制终止。

        参数:
            instance: 要关闭的实例。
            timeout: 等待正常退出的秒数。

        异常:
            ValueError: 超时小于 0。
        """
        if timeout < 0:
            raise ValueError("timeout 不能为负数")

        with self._lock:
            prepared = self._prepare_shutdown(instance)
        if isinstance(prepared, ShutdownResult):
            return prepared

        pid, create_time = prepared
        method = request_graceful_close(pid)
        self._logger.info(
            "关闭游戏 [%s] pid=%s method=%s",
            instance.instance_name,
            pid,
            method,
        )
        exited = self._wait_until_exit(instance.instance_id, pid, create_time, timeout)
        with self._lock:
            if not self._is_current_identity(instance.instance_id, pid, create_time):
                message = "关闭过程中该实例已重新启动，已保留新的进程"
                return ShutdownResult(instance.instance_id, False, message, method=method)
            inspection = self._inspect(pid, create_time)
            if inspection == ProcessIdentity.MISMATCH:
                return self._refuse_mismatched_identity(instance, pid)
            if exited or inspection != ProcessIdentity.MATCH:
                self._mark_stopped(instance)
                self._logger.info("关闭游戏完成 [%s]", instance.instance_name)
                return ShutdownResult(
                    instance.instance_id,
                    True,
                    "进程已退出",
                    method=method,
                )

            message = "正常关闭超时，进程仍在运行。未强制结束，请确认是否继续处理。"
            instance.last_error = message
            self._set_status(instance, InstanceStatus.RUNNING)
            self._logger.warning("正常关闭超时 [%s] pid=%s，未强制结束", instance.instance_name, pid)
            return ShutdownResult(
                instance.instance_id,
                False,
                message,
                timed_out=True,
                needs_user_decision=True,
                method=method,
            )

    def shutdown_all(self, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT) -> list[ShutdownResult]:
        """逐个正常关闭本管理器正在跟踪的实例。

        不会扫描同名可执行文件，因此不会关掉其他程序启动的客户端。
        """
        results: list[ShutdownResult] = []
        for instance in self.managed_instances():
            results.append(self.shutdown(instance, timeout=timeout))
        return results

    def force_terminate(self, instance: GameInstance) -> ShutdownResult:
        """在身份核对通过后结束进程。

        这是超时后的进一步处理，只能由用户确认后再调用。
        结束前会再次读取进程创建时间；一旦 PID 已被复用，就放弃结束。
        """
        with self._lock:
            identity = self._identities.get(instance.instance_id)
            if identity is None:
                message = "拒绝强制结束：该实例不是由本程序启动或接管的"
                instance.last_error = message
                self._logger.warning("%s [%s]", message, instance.instance_name)
                return ShutdownResult(
                    instance.instance_id,
                    False,
                    message,
                    identity_mismatch=True,
                )
            pid, create_time = identity
            inspection = self._inspect(pid, create_time)
            if inspection == ProcessIdentity.EXITED:
                self._mark_stopped(instance)
                return ShutdownResult(instance.instance_id, True, "进程已退出")
            if inspection != ProcessIdentity.MATCH:
                return self._refuse_mismatched_identity(instance, pid)
            try:
                process = psutil.Process(pid)
                if abs(process.create_time() - create_time) > self._tolerance:
                    return self._refuse_mismatched_identity(instance, pid)
                process.kill()
                process.wait(timeout=3)
            except psutil.NoSuchProcess:
                pass
            except psutil.Error as exc:
                message = f"强制结束失败: {exc}"
                instance.last_error = message
                self._set_status(instance, InstanceStatus.ERROR)
                self._logger.error("强制结束失败 [%s] pid=%s: %s", instance.instance_name, pid, exc)
                return ShutdownResult(instance.instance_id, False, message)
            self._mark_stopped(instance)
            self._logger.warning("用户确认后强制结束 [%s] pid=%s", instance.instance_name, pid)
            return ShutdownResult(instance.instance_id, True, "进程已强制结束")

    def attach_persisted(self, instance: GameInstance) -> bool:
        """重启管理程序后，按已保存的 PID 和创建时间重新接管进程。

        只有两个值都与当前存活进程一致时才接管。失败时不向该进程发送任何信号。
        """
        with self._lock:
            if instance.pid is None or instance.process_create_time is None:
                self._logger.warning("拒绝接管 [%s]：缺少 PID 或进程创建时间", instance.instance_name)
                return False
            if self._is_running_unlocked(instance):
                return True
            if self._inspect(instance.pid, instance.process_create_time) != ProcessIdentity.MATCH:
                self._logger.warning(
                    "拒绝接管 [%s]：PID %s 与进程创建时间不匹配",
                    instance.instance_name,
                    instance.pid,
                )
                return False
            self._identities[instance.instance_id] = (instance.pid, instance.process_create_time)
            self._instances[instance.instance_id] = instance
            instance.last_error = None
            self._set_status(instance, InstanceStatus.RUNNING)
            self._logger.info("已接管进程 [%s] pid=%s", instance.instance_name, instance.pid)
            return True

    def _spawn(self, instance: GameInstance) -> StartResult:
        """创建子进程，确认身份，并观察它是否立刻退出。"""
        exe = Path(instance.exe_path).expanduser() if instance.exe_path else None
        if exe is None or not exe.is_file():
            return self._fail_start(instance, f"游戏可执行文件不存在: {instance.exe_path}")
        instance.exe_path = str(exe.resolve())

        command = [instance.exe_path, *instance.startup_arguments]
        kwargs: dict[str, object] = {
            "cwd": str(exe.resolve().parent),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            # 新进程组使后续控制台中断只影响这个实例，不会波及同名的其他客户端。
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        try:
            popen = subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]
        except OSError as exc:
            return self._fail_start(instance, f"启动失败: {exc}")

        try:
            process = psutil.Process(popen.pid)
            create_time = float(process.create_time())
        except psutil.Error as exc:
            self._kill_unidentified_child(popen)
            return self._fail_start(instance, f"启动后无法确认进程身份，已结束本次启动的进程: {exc}")

        with self._lock:
            instance.pid = popen.pid
            instance.process_create_time = create_time
            instance.start_time = datetime.now()
            instance.last_error = None
            self._identities[instance.instance_id] = (popen.pid, create_time)
            self._popen[instance.instance_id] = popen
            self._instances[instance.instance_id] = instance

        if self._exited_within_window(popen):
            code = popen.returncode
            message = (
                f"进程启动后立即退出（退出码 {code}）。"
                "若游戏不支持多开，请勿继续尝试绕过限制。"
            )
            with self._lock:
                self._drop_process_tracking(instance, InstanceStatus.ERROR, message)
            self._logger.error("进程异常退出 [%s] %s", instance.instance_name, message)
            return StartResult(instance.instance_id, False, message)

        with self._lock:
            self._set_status(instance, InstanceStatus.RUNNING)
        self._logger.info(
            "启动游戏 [%s] pid=%s exe=%s",
            instance.instance_name,
            instance.pid,
            instance.exe_path,
        )
        return StartResult(instance.instance_id, True, "启动成功", instance.pid)

    def _exited_within_window(self, popen: subprocess.Popen[bytes]) -> bool:
        """在观察窗口内等待。进程退出返回 True，仍存活返回 False。"""
        try:
            popen.wait(timeout=self._quick_exit_window)
        except subprocess.TimeoutExpired:
            return False
        return True

    def _prepare_shutdown(self, instance: GameInstance) -> tuple[int, float] | ShutdownResult:
        """在锁内确认关闭目标。返回应关闭的身份，或一个已经完成的结果。"""
        identity = self._identities.get(instance.instance_id)
        if identity is None:
            if instance.pid is None:
                self._set_status(instance, InstanceStatus.STOPPED)
                return ShutdownResult(instance.instance_id, True, "实例未在运行")
            message = "拒绝关闭：该进程不是由本程序启动或接管的"
            instance.last_error = message
            self._logger.warning("%s [%s] pid=%s", message, instance.instance_name, instance.pid)
            return ShutdownResult(
                instance.instance_id,
                False,
                message,
                identity_mismatch=True,
            )

        pid, create_time = identity
        # 以启动时记录的身份为准，忽略事后被改写到其他进程上的 PID。
        instance.pid = pid
        instance.process_create_time = create_time
        inspection = self._inspect(pid, create_time)
        if inspection == ProcessIdentity.EXITED:
            self._mark_stopped(instance)
            self._logger.info("进程异常退出 [%s] pid=%s 已不存在", instance.instance_name, pid)
            return ShutdownResult(instance.instance_id, True, "进程已退出")
        if inspection == ProcessIdentity.MISMATCH:
            return self._refuse_mismatched_identity(instance, pid)
        if inspection == ProcessIdentity.INACCESSIBLE:
            message = f"无法读取 PID {pid} 的进程信息，已拒绝关闭"
            instance.last_error = message
            self._set_status(instance, InstanceStatus.ERROR)
            self._logger.error(message)
            return ShutdownResult(instance.instance_id, False, message, identity_mismatch=True)

        self._set_status(instance, InstanceStatus.STOPPING)
        return pid, create_time

    def _wait_until_exit(
        self,
        instance_id: str,
        pid: int,
        create_time: float,
        timeout: float,
    ) -> bool:
        """等待指定身份的进程退出。超时仍存活时返回 False。"""
        deadline = time.monotonic() + timeout
        while True:
            if self._poll_exited(instance_id, pid, create_time):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def _poll_exited(self, instance_id: str, pid: int, create_time: float) -> bool:
        """查看子进程句柄和系统进程表，判断原进程是否已经结束。"""
        with self._lock:
            popen = self._popen.get(instance_id)
            if popen is not None and popen.poll() is not None:
                return True
            return self._inspect(pid, create_time) != ProcessIdentity.MATCH

    def _refuse_mismatched_identity(self, instance: GameInstance, pid: int) -> ShutdownResult:
        """身份不一致时停止操作，避免结束复用了该 PID 的其他进程。"""
        message = (
            f"PID {pid} 的进程创建时间与启动时记录不一致，可能已被系统复用。"
            "已拒绝关闭，以避免误结束其他进程。"
        )
        instance.last_error = message
        instance.pid = None
        instance.process_create_time = None
        self._set_status(instance, InstanceStatus.ERROR)
        self._logger.error("进程身份不匹配 [%s] %s", instance.instance_name, message)
        return ShutdownResult(
            instance.instance_id,
            False,
            message,
            identity_mismatch=True,
        )

    def _fail_start(self, instance: GameInstance, message: str) -> StartResult:
        """记录启动失败并返回失败结果。"""
        with self._lock:
            instance.last_error = message
            instance.pid = None
            instance.process_create_time = None
            self._identities.pop(instance.instance_id, None)
            self._popen.pop(instance.instance_id, None)
            self._instances.pop(instance.instance_id, None)
            self._set_status(instance, InstanceStatus.ERROR)
        self._logger.error("启动失败 [%s] %s", instance.instance_name, message)
        return StartResult(instance.instance_id, False, message)

    def _drop_process_tracking(
        self,
        instance: GameInstance,
        status: InstanceStatus,
        message: str,
    ) -> None:
        """立即退出的进程不再继续跟踪，只保留错误说明。"""
        instance.last_error = message
        instance.pid = None
        instance.process_create_time = None
        self._identities.pop(instance.instance_id, None)
        self._popen.pop(instance.instance_id, None)
        self._instances.pop(instance.instance_id, None)
        self._set_status(instance, status)

    def _mark_stopped(self, instance: GameInstance) -> None:
        """确认原进程结束后清除运行时身份。"""
        instance.pid = None
        instance.process_create_time = None
        instance.last_error = None
        self._identities.pop(instance.instance_id, None)
        self._popen.pop(instance.instance_id, None)
        self._instances.pop(instance.instance_id, None)
        self._set_status(instance, InstanceStatus.STOPPED)

    def _set_status(self, instance: GameInstance, status: InstanceStatus) -> None:
        """修改状态，并在状态真正变化时写日志。"""
        previous = instance.status
        instance.status = status
        if previous != status:
            self._logger.info(
                "状态变化 [%s] %s -> %s",
                instance.instance_name,
                previous.value,
                status.value,
            )

    def _is_running_unlocked(self, instance: GameInstance) -> bool:
        """在已持有锁时判断记录中的进程是否仍然匹配。"""
        identity = self._identities.get(instance.instance_id)
        if identity is None:
            return False
        popen = self._popen.get(instance.instance_id)
        if popen is not None and popen.poll() is not None:
            return False
        return self._inspect(identity[0], identity[1]) == ProcessIdentity.MATCH

    def _is_current_identity(self, instance_id: str, pid: int, create_time: float) -> bool:
        """确认等待期间没有被一次新的启动替换掉。"""
        current = self._identities.get(instance_id)
        if current is None:
            return False
        return current[0] == pid and abs(current[1] - create_time) <= self._tolerance

    def _inspect(self, pid: int, create_time: float) -> ProcessIdentity:
        """核对系统中的进程是否仍是记录中的那一个。"""
        try:
            process = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return ProcessIdentity.EXITED
        except psutil.AccessDenied:
            return ProcessIdentity.INACCESSIBLE
        try:
            if process.status() == psutil.STATUS_ZOMBIE:
                return ProcessIdentity.EXITED
            actual_create_time = float(process.create_time())
        except psutil.NoSuchProcess:
            return ProcessIdentity.EXITED
        except psutil.AccessDenied:
            return ProcessIdentity.INACCESSIBLE
        if abs(actual_create_time - create_time) <= self._tolerance:
            return ProcessIdentity.MATCH
        return ProcessIdentity.MISMATCH

    @staticmethod
    def _kill_unidentified_child(popen: subprocess.Popen[bytes]) -> None:
        """结束刚刚由本次调用创建、但还没能记录身份的子进程。"""
        try:
            popen.kill()
            popen.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            return
