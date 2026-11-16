from __future__ import annotations

import json
from pathlib import Path

from app.db import connect, fixtures_dir


SCHEMA = """
CREATE TABLE IF NOT EXISTS domains (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  biz_key TEXT NOT NULL,
  fixture_file TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS layer_paste (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  biz_day TEXT NOT NULL,
  store_code TEXT NOT NULL,
  store_name TEXT NOT NULL,
  category TEXT NOT NULL,
  amount REAL NOT NULL,
  qty INTEGER NOT NULL,
  raw_json TEXT NOT NULL,
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

CREATE TABLE IF NOT EXISTS layer_detail (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  biz_day TEXT NOT NULL,
  store_code TEXT NOT NULL,
  store_name TEXT NOT NULL,
  category TEXT NOT NULL,
  amount REAL NOT NULL,
  qty INTEGER NOT NULL,
  clean_flag TEXT NOT NULL,
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

CREATE TABLE IF NOT EXISTS layer_summary (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  biz_day TEXT NOT NULL,
  store_code TEXT NOT NULL,
  amount_sum REAL NOT NULL,
  qty_sum INTEGER NOT NULL,
  line_count INTEGER NOT NULL,
  UNIQUE(domain_id, biz_day, store_code),
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

CREATE TABLE IF NOT EXISTS layer_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  step TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '',
  in_count INTEGER NOT NULL DEFAULT 0,
  out_count INTEGER NOT NULL DEFAULT 0,
  drop_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

CREATE TABLE IF NOT EXISTS reconcile_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  paste_count INTEGER NOT NULL,
  detail_count INTEGER NOT NULL,
  summary_line_sum INTEGER NOT NULL,
  key_mismatch INTEGER NOT NULL,
  amount_drift REAL NOT NULL,
  status TEXT NOT NULL,
  detail_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

-- 差异清单：每次对账报告物化一份不可变快照，按报告 id 关联。
CREATE TABLE IF NOT EXISTS reconcile_diff_lists (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_id INTEGER NOT NULL UNIQUE,
  domain_id INTEGER NOT NULL,
  key_count INTEGER NOT NULL DEFAULT 0,
  detail_only_count INTEGER NOT NULL DEFAULT 0,
  summary_only_count INTEGER NOT NULL DEFAULT 0,
  count_mismatch_count INTEGER NOT NULL DEFAULT 0,
  amount_drift_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(report_id) REFERENCES reconcile_reports(id),
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

CREATE TABLE IF NOT EXISTS reconcile_diff_keys (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  list_id INTEGER NOT NULL,
  biz_day TEXT NOT NULL,
  store_code TEXT NOT NULL,
  diff_kind TEXT NOT NULL,
  detail_line_count INTEGER NOT NULL DEFAULT 0,
  detail_amount REAL NOT NULL DEFAULT 0,
  summary_line_count INTEGER NOT NULL DEFAULT 0,
  summary_amount REAL NOT NULL DEFAULT 0,
  amount_delta REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(list_id, biz_day, store_code),
  FOREIGN KEY(list_id) REFERENCES reconcile_diff_lists(id)
);

-- 按键重算报告：外键挂差异清单 id，只覆盖清单内键。
CREATE TABLE IF NOT EXISTS recompute_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain_id INTEGER NOT NULL,
  report_id INTEGER NOT NULL,
  diff_list_id INTEGER NOT NULL,
  scope TEXT NOT NULL,
  commit_mode TEXT NOT NULL,
  status TEXT NOT NULL,
  key_total INTEGER NOT NULL DEFAULT 0,
  key_success INTEGER NOT NULL DEFAULT 0,
  key_failed INTEGER NOT NULL DEFAULT 0,
  message TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at TEXT,
  FOREIGN KEY(domain_id) REFERENCES domains(id),
  FOREIGN KEY(report_id) REFERENCES reconcile_reports(id),
  FOREIGN KEY(diff_list_id) REFERENCES reconcile_diff_lists(id)
);

CREATE TABLE IF NOT EXISTS recompute_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  diff_key_id INTEGER,
  biz_day TEXT NOT NULL,
  store_code TEXT NOT NULL,
  status TEXT NOT NULL,
  action TEXT NOT NULL DEFAULT '',
  detail_line_count INTEGER NOT NULL DEFAULT 0,
  detail_amount REAL NOT NULL DEFAULT 0,
  before_existed INTEGER NOT NULL DEFAULT 0,
  before_line_count INTEGER,
  before_amount REAL,
  after_line_count INTEGER,
  after_amount REAL,
  message TEXT NOT NULL DEFAULT '',
  FOREIGN KEY(run_id) REFERENCES recompute_runs(id),
  FOREIGN KEY(diff_key_id) REFERENCES reconcile_diff_keys(id)
);

-- 下钻重算证明：每次按键重算结束时由数据库现算落一行，供按报告 id / 重算任务 id 只读下钻。
-- 差异键数取差异清单计数；重算键数与成败取 recompute_items 实际逐键结果；
-- 越界写回键数应为 0，用于证明只重写了清单内键。
CREATE TABLE IF NOT EXISTS recompute_proofs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL UNIQUE,
  report_id INTEGER NOT NULL,
  diff_list_id INTEGER NOT NULL,
  domain_id INTEGER NOT NULL,
  diff_key_count INTEGER NOT NULL,
  recomputed_key_count INTEGER NOT NULL,
  success_key_count INTEGER NOT NULL,
  failed_key_count INTEGER NOT NULL,
  out_of_list_key_count INTEGER NOT NULL DEFAULT 0,
  complete INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES recompute_runs(id),
  FOREIGN KEY(report_id) REFERENCES reconcile_reports(id),
  FOREIGN KEY(diff_list_id) REFERENCES reconcile_diff_lists(id),
  FOREIGN KEY(domain_id) REFERENCES domains(id)
);

CREATE INDEX IF NOT EXISTS idx_diff_keys_list ON reconcile_diff_keys(list_id);
CREATE INDEX IF NOT EXISTS idx_recompute_runs_report ON recompute_runs(report_id);
CREATE INDEX IF NOT EXISTS idx_recompute_items_run ON recompute_items(run_id);
CREATE INDEX IF NOT EXISTS idx_recompute_proofs_report ON recompute_proofs(report_id);
"""


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT COUNT(*) AS c FROM domains").fetchone()
        if int(row["c"]) == 0:
            _seed_domain(conn)
        conn.commit()
    finally:
        conn.close()


def _seed_domain(conn) -> None:
    fixture = "门店日销售-贴源.jsonl"
    cur = conn.execute(
        """
        INSERT INTO domains(name, biz_key, fixture_file, description)
        VALUES (?, ?, ?, ?)
        """,
        (
            "门店日销售",
            "业务日+门店编码",
            fixture,
            "演示贴源装载、明细清洗与按门店日汇总",
        ),
    )
    domain_id = int(cur.lastrowid)
    path = fixtures_dir() / fixture
    if not path.exists():
        # 仓库内相对路径兜底
        alt = Path(__file__).resolve().parents[2] / "fixtures" / fixture
        path = alt
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        conn.execute(
            """
            INSERT INTO layer_paste(
              domain_id, biz_day, store_code, store_name, category, amount, qty, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                domain_id,
                obj.get("业务日") or "",
                obj.get("门店编码") or "",
                obj.get("门店名称") or "",
                obj.get("品类") or "",
                float(obj.get("金额") or 0),
                int(obj.get("件数") or 0),
                json.dumps(obj, ensure_ascii=False),
            ),
        )
