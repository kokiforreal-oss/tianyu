"""客户端目录扫描测试。使用临时文件，不读取真实游戏客户端。"""

from __future__ import annotations

import json

from analyzer.client_analyzer import ClientAnalyzer


def test_scan_classifies_files_and_writes_inventory(tmp_path) -> None:
    """按扩展名分类，配置文件单独标出，未知文件只保留元信息。"""
    root = tmp_path / "client"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "game.exe").write_bytes(b"MZ-fake")
    (root / "bin" / "engine.dll").write_bytes(b"dll")
    (root / "config.ini").write_text("volume=1\n", encoding="utf-8")
    (root / "user.cfg").write_text("width=800\n", encoding="utf-8")
    (root / "data.dat").write_bytes(b"\x00\x01")
    (root / "pack.pak").write_bytes(b"PK")
    unknown = root / "raw.bin"
    original = b"\x7funknown-resource"
    unknown.write_bytes(original)

    inventory = ClientAnalyzer().scan(root)
    by_name = {item.name: item for item in inventory.files}

    assert by_name["game.exe"].category == "EXE"
    assert by_name["engine.dll"].category == "DLL"
    assert by_name["config.ini"].category == "INI"
    assert by_name["config.ini"].is_config is True
    assert by_name["user.cfg"].category == "OTHER"
    assert by_name["user.cfg"].is_config is True
    assert by_name["data.dat"].category == "DAT"
    assert by_name["pack.pak"].category == "PAK"
    assert by_name["raw.bin"].category == "OTHER"
    assert by_name["raw.bin"].metadata_only is True
    assert by_name["raw.bin"].parsed is False
    assert by_name["raw.bin"].size_bytes == len(original)
    assert unknown.read_bytes() == original
    assert all(item.parsed is False for item in inventory.files)
    assert by_name["game.exe"].relative_path == "bin/game.exe"

    destination = tmp_path / "out" / "inventory.json"
    inventory.write_json(destination)
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["file_count"] == 7
    assert payload["files"][0]["source"].endswith("config.ini") or any(
        item["name"] == "raw.bin" and item["metadata_only"] for item in payload["files"]
    )


def test_scan_rejects_missing_directory(tmp_path) -> None:
    """目录不存在时不创建它，也不返回空清单冒充扫描成功。"""
    missing = tmp_path / "missing-client"
    try:
        ClientAnalyzer().scan(missing)
    except NotADirectoryError as exc:
        assert "missing-client" in str(exc)
    else:
        raise AssertionError("不存在的目录应当拒绝扫描")
    assert not missing.exists()
