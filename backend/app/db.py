from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def _data_dir() -> Path:
    return Path(
        os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data")
    )


def fixtures_dir() -> Path:
    return Path(
        os.environ.get(
            "FIXTURES_DIR", Path(__file__).resolve().parents[2] / "fixtures"
        )
    )


def db_path() -> Path:
    # 每次连接时按当前 DATA_DIR 解析，便于测试与容器挂载切换数据目录。
    return _data_dir() / "app.db"


def connect() -> sqlite3.Connection:
    _data_dir().mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]
