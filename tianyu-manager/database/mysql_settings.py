"""读取 MySQL 连接设置。密码优先来自环境变量，不写进代码。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


class MysqlConfigError(ValueError):
    """连接分析库所需的配置不完整。"""


@dataclass(slots=True)
class MysqlSettings:
    """分析库连接信息。"""

    host: str
    port: int
    user: str
    password: str
    database: str


def load_mysql_settings(config_path: Path | str | None = None) -> MysqlSettings:
    """从环境变量和 config.yaml 的 mysql 段组装连接信息。

    环境变量覆盖同名配置。用户或数据库名为空时直接拒绝连接，
    避免连到一个未声明的库。

    环境变量:
        TIANYU_MYSQL_HOST、TIANYU_MYSQL_PORT、TIANYU_MYSQL_USER、
        TIANYU_MYSQL_PASSWORD、TIANYU_MYSQL_DATABASE。
    """
    file_settings: dict[str, object] = {}
    if config_path is not None:
        path = Path(config_path)
        if path.is_file():
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict) and isinstance(loaded.get("mysql"), dict):
                file_settings = loaded["mysql"]

    host = os.environ.get("TIANYU_MYSQL_HOST", str(file_settings.get("host") or "127.0.0.1"))
    port_text = os.environ.get("TIANYU_MYSQL_PORT", str(file_settings.get("port") or "3306"))
    user = os.environ.get("TIANYU_MYSQL_USER", str(file_settings.get("user") or ""))
    password = os.environ.get("TIANYU_MYSQL_PASSWORD", str(file_settings.get("password") or ""))
    database = os.environ.get("TIANYU_MYSQL_DATABASE", str(file_settings.get("database") or ""))
    if not user.strip() or not database.strip():
        raise MysqlConfigError("MySQL 用户和数据库名需要在环境变量或 config.yaml 的 mysql 段中填写")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise MysqlConfigError(f"MySQL 端口不是整数: {port_text}") from exc
    return MysqlSettings(
        host=host.strip(),
        port=port,
        user=user.strip(),
        password=password,
        database=database.strip(),
    )


def connect_mysql(settings: MysqlSettings):
    """按设置连接 MySQL。PyMySQL 只在真正连接时导入。"""
    import pymysql

    return pymysql.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
        charset="utf8mb4",
        autocommit=False,
    )
