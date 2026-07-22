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
