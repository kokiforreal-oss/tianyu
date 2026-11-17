"""扫描游戏客户端目录，只记录文件元信息。"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

# 按扩展名归档。无法识别的文件归入 OTHER，不根据文件内容猜测格式。
_CATEGORY_BY_SUFFIX = {
    ".exe": "EXE",
    ".dll": "DLL",
    ".ini": "INI",
    ".dat": "DAT",
    ".pak": "PAK",
}

# 这些扩展名只表示“像配置文件”，本扫描器不会打开并解释其中的键值。
_CONFIG_SUFFIXES = {
    ".ini",
    ".cfg",
    ".conf",
    ".xml",
    ".json",
    ".yaml",
    ".yml",
    ".properties",
    ".toml",
}


@dataclass(slots=True)
class FileRecord:
    """目录扫描得到的一条文件记录。

    `parsed` 固定为 False：当前阶段不读取文件内容，因此也不修改文件。
    """

    relative_path: str
    name: str
    extension: str
    size_bytes: int
    modified_time: str
    category: str
    is_config: bool
    metadata_only: bool
    parsed: bool
    source: str


@dataclass(slots=True)
class ClientInventory:
    """一次客户端目录扫描的结果。"""

    root: str
    scanned_at: str
    files: list[FileRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """转换成可写入 JSON 的字典。来源保留扫描到的绝对路径。"""
        return {
            "root": self.root,
            "scanned_at": self.scanned_at,
            "file_count": len(self.files),
            "files": [asdict(item) for item in self.files],
            "errors": list(self.errors),
        }

    def write_json(self, path: Path) -> None:
        """把资源清单写成 UTF-8 JSON。不会回写被扫描的客户端目录。"""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class ClientAnalyzer:
    """只读扫描用户指定的客户端目录。"""

    def scan(self, root: Path | str) -> ClientInventory:
        """扫描目录下的文件名、扩展名、大小和修改时间。

        不打开文件内容，不跟随目录符号链接，也不写入该目录。
        未知扩展名只记为 OTHER，不会被当成已经识别的资源格式。

        参数:
            root: 用户选择的客户端根目录。

        异常:
            NotADirectoryError: 路径不存在或不是目录。
        """
        directory = Path(root)
        if not directory.is_dir():
            raise NotADirectoryError(f"客户端目录不存在或不是目录: {directory}")
        resolved = directory.resolve()
        inventory = ClientInventory(
            root=str(resolved),
            scanned_at=datetime.now().isoformat(timespec="seconds"),
        )
        for current, dir_names, file_names in os.walk(resolved, followlinks=False):
            dir_names.sort()
            file_names.sort()
            for file_name in file_names:
                path = Path(current) / file_name
                self._append_file(resolved, path, inventory)
        inventory.files.sort(key=lambda item: item.relative_path)
        return inventory

    def _append_file(self, root: Path, path: Path, inventory: ClientInventory) -> None:
        """记录一个文件的元信息。读取失败时写入 errors，不中断整次扫描。"""
        try:
            stat_result = path.lstat()
        except OSError as exc:
            inventory.errors.append(f"{path}: {exc}")
            return
        if not stat.S_ISREG(stat_result.st_mode):
            return
        suffix = path.suffix.lower()
        is_config = suffix in _CONFIG_SUFFIXES
        category = _CATEGORY_BY_SUFFIX.get(suffix, "OTHER")
        # 配置文件只做归类。二进制和未知文件连内容都不读取。
        metadata_only = not is_config
        modified = datetime.fromtimestamp(stat_result.st_mtime).isoformat(timespec="seconds")
        inventory.files.append(
            FileRecord(
                relative_path=path.relative_to(root).as_posix(),
                name=path.name,
                extension=suffix,
                size_bytes=stat_result.st_size,
                modified_time=modified,
                category=category,
                is_config=is_config,
                metadata_only=metadata_only,
                parsed=False,
                source=str(path),
            )
        )
