"""按日期写入运行日志。"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


def log_file_path(log_dir: Path, now: datetime | None = None) -> Path:
    """返回某一天对应的日志文件路径。

    参数:
        log_dir: 日志目录。
        now: 用于计算日期的时间。测试可以传入固定时间。
    """
    current = now or datetime.now()
    return Path(log_dir) / f"tianyu-manager-{current:%Y-%m-%d}.log"


class DailyFileHandler(logging.Handler):
    """把日志追加到当天的文件，跨过零点后自动换新文件。"""

    def __init__(self, log_dir: Path) -> None:
        super().__init__()
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._current_date = ""
        self._stream = None
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        """写入一条日志。文件按本地日期打开。"""
        try:
            date_text = datetime.now().strftime("%Y-%m-%d")
            if date_text != self._current_date or self._stream is None:
                self._open(date_text)
            message = self.format(record)
            assert self._stream is not None
            self._stream.write(message + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def _open(self, date_text: str) -> None:
        """切换到指定日期的日志文件。"""
        if self._stream is not None:
            self._stream.close()
        self._stream = log_file_path(self.log_dir, _date_from_text(date_text)).open(
            "a",
            encoding="utf-8",
        )
        self._current_date = date_text

    def close(self) -> None:
        """关闭当前日志文件。"""
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        super().close()


def _date_from_text(date_text: str) -> datetime:
    """把 `YYYY-MM-DD` 转成日期，供路径函数复用。"""
    return datetime.strptime(date_text, "%Y-%m-%d")


def attach_daily_file_logger(logger: logging.Logger, log_dir: Path) -> DailyFileHandler:
    """给指定 logger 挂上按日期切分的文件处理器。

    参数:
        logger: 要接收日志的记录器。
        log_dir: 日志目录，不存在时会创建。

    返回:
        已挂上的处理器，调用方负责在退出时关闭并移除。
    """
    handler = DailyFileHandler(log_dir)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return handler
