"""
Copyright (C) 2026 123panNextGen
[https://github.com/123panNextGen/123pan]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Generator[Path, Any, None]:
    """Provide a temporary CONFIG_DIR to isolate ConfigManager tests."""
    import src.app.common.config as config_mod

    original = config_mod.CONFIG_DIR
    config_mod.CONFIG_DIR = tmp_path / "123pan"
    config_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    yield config_mod.CONFIG_DIR
    config_mod.CONFIG_DIR = original


@pytest.fixture
def tmp_db(tmp_path: Path) -> Generator[Path, Any, None]:
    """提供隔离的 SQLite 数据库与配置目录。

    同时重定向 ConfigManager 的 CONFIG_DIR/CONFIG_FILE、
    Database 的存储路径，并重置单例，避免污染真实配置。
    """
    import src.app.common.config as config_mod
    import src.app.common.file_list_db as fldb_mod
    from src.app.common.database import Database

    original_config_dir = config_mod.CONFIG_DIR
    original_config_file = config_mod.CONFIG_FILE
    original_fldb_path = fldb_mod.FILE_DB_PATH

    config_mod.CONFIG_DIR = tmp_path / "123pan"
    config_mod.CONFIG_FILE = config_mod.CONFIG_DIR / "config.json"
    config_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fldb_mod.FILE_DB_PATH = config_mod.CONFIG_DIR / "file_list_db.json"
    Database.set_path(config_mod.CONFIG_DIR / "123pan.db")
    # 确保 FileListDB 单例在路径切换后重建连接
    fldb_mod.FileListDB._instance = None

    yield config_mod.CONFIG_DIR

    Database.reset()
    fldb_mod.FileListDB._instance = None
    config_mod.CONFIG_DIR = original_config_dir
    config_mod.CONFIG_FILE = original_config_file
    fldb_mod.FILE_DB_PATH = original_fldb_path
