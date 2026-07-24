from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from config import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)


def save(name: str, data: dict[str, Any]) -> Path:
    cfg  = get_settings()
    cfg.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    target = cfg.checkpoint_dir / name

    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(cfg.checkpoint_dir), suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        os.replace(tmp_path, str(target))
        logger.debug("Checkpoint saved: %s", target)
        return target

    except OSError as exc:
        logger.warning("Failed to save checkpoint %r: %s", name, exc)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load(name: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg  = get_settings()
    path = cfg.checkpoint_dir / name

    if not path.exists():
        logger.debug("Checkpoint %r not found — returning default.", name)
        return default if default is not None else {}

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        logger.debug("Checkpoint loaded: %s (%d keys)", path, len(data))
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load checkpoint %r: %s — returning default.", name, exc)
        return default if default is not None else {}


def delete(name: str) -> bool:
    cfg  = get_settings()
    path = cfg.checkpoint_dir / name
    try:
        path.unlink()
        logger.debug("Checkpoint deleted: %s", path)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("Failed to delete checkpoint %r: %s", name, exc)
        return False


def exists(name: str) -> bool:
    cfg = get_settings()
    return (cfg.checkpoint_dir / name).exists()


def list_checkpoints() -> list[str]:
    cfg = get_settings()
    if not cfg.checkpoint_dir.exists():
        return []
    return [p.name for p in cfg.checkpoint_dir.iterdir() if p.is_file()]
