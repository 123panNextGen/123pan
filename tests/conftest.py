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
