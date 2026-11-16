from __future__ import annotations

import json

from app.db import connect, rows_to_dicts


STEP_LABEL = {
    "paste_to_detail": "贴源到明细",
    "detail_to_summary": "明细到汇总",
}


def list_domains() -> list[dict]:
    conn = connect()
    try:
        return rows_to_dicts(conn.execute("SELECT * FROM domains ORDER BY id").fetchall())
    finally:
        conn.close()


def get_domain(domain_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM domains WHERE id=?", (domain_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def layer_rows(table: str, domain_id: int | None = None) -> list[dict]:
    allowed = {
        "paste": "layer_paste",
        "detail": "layer_detail",
        "summary": "layer_summary",
    }
    if table not in allowed:
        raise ValueError("未知分层")
    sql = f"SELECT * FROM {allowed[table]}"
    args: tuple = ()
    if domain_id is not None:
        sql += " WHERE domain_id=?"
        args = (domain_id,)
    sql += " ORDER BY id"
    conn = connect()
    try:
        return rows_to_dicts(conn.execute(sql, args).fetchall())
    finally:
        conn.close()


def layer_counts(domain_id: int | None = None) -> dict:
    conn = connect()
    try:
        where = " WHERE domain_id=?" if domain_id is not None else ""
        args = (domain_id,) if domain_id is not None else ()
        paste = conn.execute(f"SELECT COUNT(*) AS c FROM layer_paste{where}", args).fetchone()["c"]
        detail = conn.execute(f"SELECT COUNT(*) AS c FROM layer_detail{where}", args).fetchone()["c"]
        summary = conn.execute(f"SELECT COUNT(*) AS c FROM layer_summary{where}", args).fetchone()["c"]
        return {
            "贴源层": int(paste),
            "明细层": int(detail),
            "汇总层": int(summary),
        }
    finally:
        conn.close()


def list_jobs(domain_id: int | None = None) -> list[dict]:
    conn = connect()
    try:
        if domain_id is None:
            rows = conn.execute("SELECT * FROM layer_jobs ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM layer_jobs WHERE domain_id=? ORDER BY id DESC", (domain_id,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["step_label"] = STEP_LABEL.get(d["step"], d["step"])
            out.append(d)
        return out
    finally:
        conn.close()


def run_paste_to_detail(domain_id: int) -> dict:
    domain = get_domain(domain_id)
    if not domain:
        raise ValueError("主题域不存在")
    conn = connect()
    try:
        conn.execute("DELETE FROM layer_detail WHERE domain_id=?", (domain_id,))
        paste = conn.execute(
            "SELECT * FROM layer_paste WHERE domain_id=? ORDER BY id", (domain_id,)
        ).fetchall()
        out = drop = 0
        for row in paste:
            store_name = (row["store_name"] or "").strip()
            amount = float(row["amount"])
            if not store_name or amount < 0:
                drop += 1
                continue
            conn.execute(
                """
                INSERT INTO layer_detail(
                  domain_id, biz_day, store_code, store_name, category, amount, qty, clean_flag
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    domain_id,
                    row["biz_day"],
                    row["store_code"],
                    store_name,
                    row["category"],
                    amount,
                    int(row["qty"]),
                    "已清洗",
                ),
            )
            out += 1
        cur = conn.execute(
            """
            INSERT INTO layer_jobs(domain_id, step, status, message, in_count, out_count, drop_count)
            VALUES (?, 'paste_to_detail', '成功', ?, ?, ?, ?)
            """,
            (domain_id, f"清洗完成，剔除门店名为空或金额为负的行", len(paste), out, drop),
        )
        conn.commit()
        job_id = int(cur.lastrowid)
        return dict(conn.execute("SELECT * FROM layer_jobs WHERE id=?", (job_id,)).fetchone())
    finally:
        conn.close()


def run_detail_to_summary(domain_id: int) -> dict:
    domain = get_domain(domain_id)
    if not domain:
        raise ValueError("主题域不存在")
    conn = connect()
    try:
        conn.execute("DELETE FROM layer_summary WHERE domain_id=?", (domain_id,))
        detail = conn.execute(
            "SELECT * FROM layer_detail WHERE domain_id=? ORDER BY id", (domain_id,)
        ).fetchall()
        buckets: dict[tuple, dict] = {}
        for row in detail:
            key = (row["biz_day"], row["store_code"])
            b = buckets.setdefault(
                key,
                {"biz_day": row["biz_day"], "store_code": row["store_code"], "amount": 0.0, "qty": 0, "n": 0},
            )
            b["amount"] += float(row["amount"])
            b["qty"] += int(row["qty"])
            b["n"] += 1
        for b in buckets.values():
            conn.execute(
                """
                INSERT INTO layer_summary(
                  domain_id, biz_day, store_code, amount_sum, qty_sum, line_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (domain_id, b["biz_day"], b["store_code"], b["amount"], b["qty"], b["n"]),
            )
        cur = conn.execute(
            """
            INSERT INTO layer_jobs(domain_id, step, status, message, in_count, out_count, drop_count)
            VALUES (?, 'detail_to_summary', '成功', ?, ?, ?, 0)
            """,
            (domain_id, "按业务日+门店编码汇总", len(detail), len(buckets)),
        )
        conn.commit()
        job_id = int(cur.lastrowid)
        return dict(conn.execute("SELECT * FROM layer_jobs WHERE id=?", (job_id,)).fetchone())
    finally:
        conn.close()


DIFF_AMOUNT_TOLERANCE = 0.0001

DIFF_KIND_DETAIL_ONLY = "仅明细有"
DIFF_KIND_SUMMARY_ONLY = "仅汇总有"
DIFF_KIND_LINE_COUNT = "行数不符"
DIFF_KIND_AMOUNT = "金额漂移"


def _detail_aggregates(conn, domain_id: int) -> dict[tuple[str, str], dict]:
    rows = conn.execute(
        """
        SELECT biz_day, store_code, COUNT(*) AS line_count, COALESCE(SUM(amount), 0) AS amount
        FROM layer_detail WHERE domain_id=?
        GROUP BY biz_day, store_code
        """,
        (domain_id,),
    ).fetchall()
    return {
        (r["biz_day"], r["store_code"]): {
            "line_count": int(r["line_count"]),
            "amount": float(r["amount"]),
        }
        for r in rows
    }


def _summary_aggregates(conn, domain_id: int) -> dict[tuple[str, str], dict]:
    rows = conn.execute(
        "SELECT biz_day, store_code, line_count, amount_sum FROM layer_summary WHERE domain_id=?",
        (domain_id,),
    ).fetchall()
    return {
        (r["biz_day"], r["store_code"]): {
            "line_count": int(r["line_count"]),
            "amount": float(r["amount_sum"]),
        }
        for r in rows
    }


def compare_layers(conn, domain_id: int) -> dict:
    """明细按键聚合与汇总逐键比较，作为差异清单、对账状态与重算的唯一来源。"""
    detail_map = _detail_aggregates(conn, domain_id)
    summary_map = _summary_aggregates(conn, domain_id)
    diff_keys: list[dict] = []
    for key in sorted(set(detail_map) | set(summary_map)):
        d = detail_map.get(key)
        s = summary_map.get(key)
        detail_lines = d["line_count"] if d else 0
        detail_amount = d["amount"] if d else 0.0
        summary_lines = s["line_count"] if s else 0
        summary_amount = s["amount"] if s else 0.0
        kinds: list[str] = []
        if d and not s:
            kinds.append(DIFF_KIND_DETAIL_ONLY)
        elif s and not d:
            kinds.append(DIFF_KIND_SUMMARY_ONLY)
        else:
            if detail_lines != summary_lines:
                kinds.append(DIFF_KIND_LINE_COUNT)
            if abs(detail_amount - summary_amount) >= DIFF_AMOUNT_TOLERANCE:
                kinds.append(DIFF_KIND_AMOUNT)
        if not kinds:
            continue
        diff_keys.append(
            {
                "biz_day": key[0],
                "store_code": key[1],
                "diff_kind": "、".join(kinds),
                "detail_line_count": detail_lines,
                "detail_amount": round(detail_amount, 4),
                "summary_line_count": summary_lines,
                "summary_amount": round(summary_amount, 4),
                "amount_delta": round(summary_amount - detail_amount, 4),
            }
        )
    return {
        "detail_map": detail_map,
        "summary_map": summary_map,
        "diff_keys": diff_keys,
    }


def _diff_counts(diff_keys: list[dict]) -> dict:
    return {
        "key_count": len(diff_keys),
        "detail_only_count": sum(
            1 for k in diff_keys if DIFF_KIND_DETAIL_ONLY in k["diff_kind"]
        ),
        "summary_only_count": sum(
            1 for k in diff_keys if DIFF_KIND_SUMMARY_ONLY in k["diff_kind"]
        ),
        "count_mismatch_count": sum(
            1 for k in diff_keys if DIFF_KIND_LINE_COUNT in k["diff_kind"]
        ),
        "amount_drift_count": sum(
            1 for k in diff_keys if DIFF_KIND_AMOUNT in k["diff_kind"]
        ),
    }


def run_reconcile(domain_id: int) -> dict:
    domain = get_domain(domain_id)
    if not domain:
        raise ValueError("主题域不存在")
    conn = connect()
    try:
        paste_count = int(
            conn.execute("SELECT COUNT(*) AS c FROM layer_paste WHERE domain_id=?", (domain_id,)).fetchone()[
                "c"
            ]
        )
        detail_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM layer_detail WHERE domain_id=?", (domain_id,)
            ).fetchone()["c"]
        )
        summary = conn.execute(
            "SELECT COALESCE(SUM(line_count),0) AS s, COALESCE(SUM(amount_sum),0) AS a FROM layer_summary WHERE domain_id=?",
            (domain_id,),
        ).fetchone()
        summary_line_sum = int(summary["s"])
        summary_amount = float(summary["a"])
        detail_amount = float(
            conn.execute(
                "SELECT COALESCE(SUM(amount),0) AS a FROM layer_detail WHERE domain_id=?",
                (domain_id,),
            ).fetchone()["a"]
        )
        compared = compare_layers(conn, domain_id)
        diff_keys = compared["diff_keys"]
        diff_counts = _diff_counts(diff_keys)
        key_mismatch = 1 if summary_line_sum != detail_count else 0
        amount_drift = round(summary_amount - detail_amount, 4)
        # 状态由逐键比较派生，而不是只看总差额：键集合错位但总额相同时也必须暴露。
        status = "一致" if not diff_keys else "存在差异"
        detail = {
            "贴源行数": paste_count,
            "明细行数": detail_count,
            "汇总行数合计": summary_line_sum,
            "明细金额合计": detail_amount,
            "汇总金额合计": summary_amount,
            "键对齐": diff_counts["detail_only_count"] == 0
            and diff_counts["summary_only_count"] == 0,
            "金额漂移": amount_drift,
            "差异键数": diff_counts["key_count"],
        }
        cur = conn.execute(
            """
            INSERT INTO reconcile_reports(
              domain_id, paste_count, detail_count, summary_line_sum, key_mismatch, amount_drift, status, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                domain_id,
                paste_count,
                detail_count,
                summary_line_sum,
                key_mismatch,
                amount_drift,
                status,
                json.dumps(detail, ensure_ascii=False),
            ),
        )
        report_id = int(cur.lastrowid)
        list_cur = conn.execute(
            """
            INSERT INTO reconcile_diff_lists(
              report_id, domain_id, key_count,
              detail_only_count, summary_only_count, count_mismatch_count, amount_drift_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                domain_id,
                diff_counts["key_count"],
                diff_counts["detail_only_count"],
                diff_counts["summary_only_count"],
                diff_counts["count_mismatch_count"],
                diff_counts["amount_drift_count"],
            ),
        )
        list_id = int(list_cur.lastrowid)
        for k in diff_keys:
            conn.execute(
                """
                INSERT INTO reconcile_diff_keys(
                  list_id, biz_day, store_code, diff_kind,
                  detail_line_count, detail_amount,
                  summary_line_count, summary_amount, amount_delta
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    list_id,
                    k["biz_day"],
                    k["store_code"],
                    k["diff_kind"],
                    k["detail_line_count"],
                    k["detail_amount"],
                    k["summary_line_count"],
                    k["summary_amount"],
                    k["amount_delta"],
                ),
            )
        conn.commit()
        return get_reconcile_report(report_id)
    finally:
        conn.close()


def list_reconcile(domain_id: int | None = None) -> list[dict]:
    conn = connect()
    try:
        if domain_id is None:
            rows = conn.execute("SELECT * FROM reconcile_reports ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM reconcile_reports WHERE domain_id=? ORDER BY id DESC",
                (domain_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d.pop("detail_json"))
            out.append(d)
        return out
    finally:
        conn.close()


def _report_row(conn, report_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM reconcile_reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["detail"] = json.loads(d.pop("detail_json"))
    return d


def _diff_list_row(conn, report_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM reconcile_diff_lists WHERE report_id=?", (report_id,)
    ).fetchone()
    return dict(row) if row else None


def _diff_key_rows(conn, list_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM reconcile_diff_keys WHERE list_id=? ORDER BY biz_day, store_code",
        (list_id,),
    ).fetchall()
    return rows_to_dicts(rows)


def _recompute_item_rows(conn, run_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM recompute_items WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall()
    return rows_to_dicts(rows)


def _recompute_run_row(conn, run_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM recompute_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    if d["diff_list_id"]:
        dl = conn.execute(
            "SELECT * FROM reconcile_diff_lists WHERE id=?", (d["diff_list_id"],)
        ).fetchone()
        d["diff_list"] = dict(dl) if dl else None
    d["items"] = _recompute_item_rows(conn, run_id)
    return d


def _write_recompute_proof(conn, run_id: int) -> dict:
    """按数据库现值生成下钻重算证明：差异键数、重算键数、成功/失败与越界写回键数。

    - 差异键数：差异清单快照里的键数（发起重算时的清单）。
    - 重算键数 / 成功 / 失败：recompute_items 实际逐键结果。
    - 越界写回键数：重算项中不在该差异清单内的键数；应恒为 0，用于证明只重写清单内键。
    """
    run = conn.execute(
        "SELECT * FROM recompute_runs WHERE id=?", (run_id,)
    ).fetchone()
    if not run:
        raise ValueError("重算任务不存在")
    list_id = int(run["diff_list_id"])
    report_id = int(run["report_id"])
    diff_key_count = int(
        conn.execute(
            "SELECT COUNT(*) AS c FROM reconcile_diff_keys WHERE list_id=?", (list_id,)
        ).fetchone()["c"]
    )
    item_counts = conn.execute(
        """
        SELECT COUNT(*) AS total,
               COALESCE(SUM(CASE WHEN status='成功' THEN 1 ELSE 0 END), 0) AS ok,
               COALESCE(SUM(CASE WHEN status='失败' THEN 1 ELSE 0 END), 0) AS bad
        FROM recompute_items WHERE run_id=?
        """,
        (run_id,),
    ).fetchone()
    recomputed = int(item_counts["total"])
    ok = int(item_counts["ok"])
    bad = int(item_counts["bad"])
    out_of_list = int(
        conn.execute(
            """
            SELECT COUNT(*) AS c FROM recompute_items i
            WHERE i.run_id=? AND NOT EXISTS (
              SELECT 1 FROM reconcile_diff_keys k
              WHERE k.list_id=? AND k.biz_day=i.biz_day AND k.store_code=i.store_code
            )
            """,
            (run_id, list_id),
        ).fetchone()["c"]
    )
    complete = 1 if recomputed == diff_key_count and out_of_list == 0 else 0
    status = "成功" if bad == 0 else ("失败" if ok == 0 else "部分失败")
    conn.execute(
        """
        INSERT INTO recompute_proofs(
          run_id, report_id, diff_list_id, domain_id,
          diff_key_count, recomputed_key_count, success_key_count, failed_key_count,
          out_of_list_key_count, complete, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
          diff_key_count=excluded.diff_key_count,
          recomputed_key_count=excluded.recomputed_key_count,
          success_key_count=excluded.success_key_count,
          failed_key_count=excluded.failed_key_count,
          out_of_list_key_count=excluded.out_of_list_key_count,
          complete=excluded.complete,
          status=excluded.status
        """,
        (
            run_id,
            report_id,
            list_id,
            int(run["domain_id"]),
            diff_key_count,
            recomputed,
            ok,
            bad,
            out_of_list,
            complete,
            status,
        ),
    )
    row = conn.execute(
        "SELECT * FROM recompute_proofs WHERE run_id=?", (run_id,)
    ).fetchone()
    return dict(row) if row else None


def _proof_rows_for_report(conn, report_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM recompute_proofs WHERE report_id=? ORDER BY id DESC",
        (report_id,),
    ).fetchall()
    return rows_to_dicts(rows)


def list_recompute_proofs(report_id: int) -> list[dict]:
    """按对账报告 id 只读下钻重算证明。"""
    conn = connect()
    try:
        if not _report_row(conn, report_id):
            raise ValueError("对账报告不存在")
        return _proof_rows_for_report(conn, report_id)
    finally:
        conn.close()


def get_recompute_proof(run_id: int) -> dict:
    """按重算任务 id 只读下钻重算证明（含逐键明细）。"""
    conn = connect()
    try:
        proof = conn.execute(
            "SELECT * FROM recompute_proofs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not proof:
            raise ValueError("该重算任务没有下钻证明")
        out = dict(proof)
        run = conn.execute(
            "SELECT * FROM recompute_runs WHERE id=?", (run_id,)
        ).fetchone()
        out["run"] = dict(run) if run else None
        out["items"] = _recompute_item_rows(conn, run_id)
        return out
    finally:
        conn.close()


def list_recompute_runs(report_id: int) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM recompute_runs WHERE report_id=? ORDER BY id DESC", (report_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["items"] = _recompute_item_rows(conn, int(r["id"]))
            out.append(d)
        return out
    finally:
        conn.close()


def current_reconcile_state(domain_id: int) -> dict:
    """按当前明细与汇总现场派生对账状态，和差异清单共用 compare_layers。"""
    if not get_domain(domain_id):
        raise ValueError("主题域不存在")
    conn = connect()
    try:
        compared = compare_layers(conn, domain_id)
        counts = _diff_counts(compared["diff_keys"])
        return {
            "domain_id": domain_id,
            "status": "一致" if not compared["diff_keys"] else "存在差异",
            "diff_key_count": counts["key_count"],
            "counts": counts,
            "diff_keys": compared["diff_keys"],
        }
    finally:
        conn.close()


def get_reconcile_report(report_id: int) -> dict:
    conn = connect()
    try:
        report = _report_row(conn, report_id)
        if not report:
            raise ValueError("对账报告不存在")
        diff_list = _diff_list_row(conn, report_id)
        if diff_list:
            diff_list["keys"] = _diff_key_rows(conn, int(diff_list["id"]))
            diff_list["recompute_runs"] = list_recompute_runs(report_id)
        return {
            "report": report,
            "diff_list": diff_list,
            "proofs": _proof_rows_for_report(conn, report_id),
            "current": current_reconcile_state(int(report["domain_id"])),
        }
    finally:
        conn.close()


def recompute_from_report(report_id: int) -> dict:
    """按差异清单逐键重算：只重写清单内键，逐键独立事务，失败键保留并标出。"""
    conn = connect()
    try:
        report = _report_row(conn, report_id)
        if not report:
            raise ValueError("对账报告不存在")
        diff_list = _diff_list_row(conn, report_id)
        if not diff_list:
            raise ValueError("该对账报告没有物化差异清单，请重新生成对账报告")
        keys = _diff_key_rows(conn, int(diff_list["id"]))
        if not keys:
            raise ValueError("该对账报告没有差异键，无需按键重算")
        domain_id = int(report["domain_id"])
        cur = conn.execute(
            """
            INSERT INTO recompute_runs(
              domain_id, report_id, diff_list_id, scope, commit_mode,
              status, key_total, message
            ) VALUES (?, ?, ?, '差异键', '逐键独立事务', '进行中', ?, ?)
            """,
            (
                domain_id,
                report_id,
                int(diff_list["id"]),
                len(keys),
                f"仅重算差异清单 {diff_list['id']} 内 {len(keys)} 个键，其它键不动",
            ),
        )
        run_id = int(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()

    success = 0
    failed = 0
    # 只遍历差异清单内的键；每个键由 _recompute_one_key 在独立事务中从明细重新聚合，
    # 不读取报告/清单里的期望值，也不触碰清单外的键。
    for key in keys:
        biz_day = key["biz_day"]
        store_code = key["store_code"]
        try:
            result = _recompute_one_key(domain_id, biz_day, store_code)
        except Exception as exc:  # 单键失败：只回滚该键，继续处理其它键
            failed += 1
            result = {
                "status": "失败",
                "action": "未写入",
                "message": str(exc),
                "after_line_count": None,
                "after_amount": None,
                "detail_line_count": 0,
                "detail_amount": 0.0,
                "before_existed": 0,
                "before_line_count": None,
                "before_amount": None,
            }
        else:
            success += 1

        conn = connect()
        try:
            conn.execute(
                """
                INSERT INTO recompute_items(
                  run_id, diff_key_id, biz_day, store_code, status, action,
                  detail_line_count, detail_amount,
                  before_existed, before_line_count, before_amount,
                  after_line_count, after_amount, message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    int(key["id"]),
                    biz_day,
                    store_code,
                    result["status"],
                    result["action"],
                    result["detail_line_count"],
                    result["detail_amount"],
                    result["before_existed"],
                    result["before_line_count"],
                    result["before_amount"],
                    result["after_line_count"],
                    result["after_amount"],
                    result["message"],
                ),
            )
            conn.execute(
                """
                UPDATE recompute_runs
                SET key_success=?, key_failed=?
                WHERE id=?
                """,
                (success, failed, run_id),
            )
            conn.commit()
        finally:
            conn.close()

    if failed == 0:
        status = "成功"
    elif success == 0:
        status = "失败"
    else:
        status = "部分失败"
    conn = connect()
    try:
        conn.execute(
            """
            UPDATE recompute_runs
            SET status=?, key_success=?, key_failed=?, finished_at=datetime('now')
            WHERE id=?
            """,
            (status, success, failed, run_id),
        )
        conn.commit()
        run = _recompute_run_row(conn, run_id)
        proof = _write_recompute_proof(conn, run_id)
        conn.commit()
    finally:
        conn.close()
    return {
        "run": run,
        "proof": proof,
        "current": current_reconcile_state(domain_id),
    }


def _recompute_one_key(domain_id: int, biz_day: str, store_code: str) -> dict:
    """单个差异键的独立事务：从明细重新聚合后覆盖该键汇总，绝不读取报告期望值。"""
    conn = connect()
    try:
        before = conn.execute(
            """
            SELECT line_count, amount_sum, qty_sum FROM layer_summary
            WHERE domain_id=? AND biz_day=? AND store_code=?
            """,
            (domain_id, biz_day, store_code),
        ).fetchone()
        agg = conn.execute(
            """
            SELECT COUNT(*) AS line_count, COALESCE(SUM(amount), 0) AS amount,
                   COALESCE(SUM(qty), 0) AS qty
            FROM layer_detail WHERE domain_id=? AND biz_day=? AND store_code=?
            """,
            (domain_id, biz_day, store_code),
        ).fetchone()
        detail_lines = int(agg["line_count"])
        detail_amount = float(agg["amount"])
        detail_qty = int(agg["qty"])

        if detail_lines == 0:
            if before is None:
                action = "无需变更"
            else:
                conn.execute(
                    """
                    DELETE FROM layer_summary
                    WHERE domain_id=? AND biz_day=? AND store_code=?
                    """,
                    (domain_id, biz_day, store_code),
                )
                action = "删除汇总"
            after_lines, after_amount = None, None
        else:
            if before is None:
                conn.execute(
                    """
                    INSERT INTO layer_summary(
                      domain_id, biz_day, store_code, amount_sum, qty_sum, line_count
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (domain_id, biz_day, store_code, detail_amount, detail_qty, detail_lines),
                )
            else:
                conn.execute(
                    """
                    UPDATE layer_summary
                    SET amount_sum=?, qty_sum=?, line_count=?
                    WHERE domain_id=? AND biz_day=? AND store_code=?
                    """,
                    (detail_amount, detail_qty, detail_lines, domain_id, biz_day, store_code),
                )
            action = "重写汇总"
            after_lines, after_amount = detail_lines, round(detail_amount, 4)
        conn.commit()
        return {
            "status": "成功",
            "action": action,
            "message": "按明细重新聚合写回" if action != "无需变更" else "明细与汇总均无该键",
            "detail_line_count": detail_lines,
            "detail_amount": round(detail_amount, 4),
            "before_existed": 1 if before is not None else 0,
            "before_line_count": int(before["line_count"]) if before is not None else None,
            "before_amount": round(float(before["amount_sum"]), 4) if before is not None else None,
            "after_line_count": after_lines,
            "after_amount": after_amount,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def dashboard() -> dict:
    domains = list_domains()
    counts = layer_counts()
    jobs = list_jobs()[:5]
    reports = list_reconcile()[:5]
    return {
        "主题域数": len(domains),
        "分层计数": counts,
        "最近任务": [
            {
                "编号": j["id"],
                "步骤": STEP_LABEL.get(j["step"], j["step"]),
                "状态": j["status"],
                "写入": j["out_count"],
                "剔除": j["drop_count"],
            }
            for j in jobs
        ],
        "最近对账": [
            {
                "编号": r["id"],
                "状态": r["status"],
                "明细行数": r["detail_count"],
                "汇总行数合计": r["summary_line_sum"],
                "差异键数": r["detail"].get("差异键数", 0),
            }
            for r in reports
        ],
        "主题域": [{"编号": d["id"], "名称": d["name"], "业务键": d["biz_key"]} for d in domains],
    }
