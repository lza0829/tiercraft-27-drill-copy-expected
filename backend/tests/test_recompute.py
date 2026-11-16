"""按差异键重算的回归测试：直接跑 SQLite，不依赖 HTTP 层。

覆盖：差异清单物化并可复查、按键重算只动清单内键、重算从明细重新聚合、
逐键独立事务的失败语义、对账状态与差异清单同源。
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest


@pytest.fixture()
def env(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmp)
    monkeypatch.setenv("FIXTURES_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "fixtures"))
    # import after env is set: app.db reads DATA_DIR at import time
    import importlib

    import app.db as db
    import app.seed as seed
    import app.services.pipeline as pipeline

    importlib.reload(db)
    importlib.reload(seed)
    importlib.reload(pipeline)
    seed.init_db()
    yield seed, pipeline
    shutil.rmtree(tmp, ignore_errors=True)


def _full_pipeline(pipeline, domain_id=1):
    pipeline.run_paste_to_detail(domain_id)
    pipeline.run_detail_to_summary(domain_id)


def _corrupt_summary(pipeline, domain_id=1):
    """模拟漂移：某键金额被改、另一个键的汇总行被删、再造一个明细没有的键。"""
    from app.db import connect

    conn = connect()
    try:
        conn.execute(
            "UPDATE layer_summary SET amount_sum = amount_sum + 999 WHERE domain_id=? AND biz_day='2026-11-10' AND store_code='S01'",
            (domain_id,),
        )
        conn.execute(
            "DELETE FROM layer_summary WHERE domain_id=? AND biz_day='2026-11-11' AND store_code='S02'",
            (domain_id,),
        )
        conn.execute(
            "INSERT INTO layer_summary(domain_id, biz_day, store_code, amount_sum, qty_sum, line_count) VALUES (?, '2026-11-10','S99', 7, 1, 1)",
            (domain_id,),
        )
        conn.commit()
    finally:
        conn.close()


def test_diff_list_materialized_and_reloads(env):
    seed, pipeline = env
    _full_pipeline(pipeline)
    _corrupt_summary(pipeline)

    created = pipeline.run_reconcile(1)
    assert created["report"]["status"] == "存在差异"
    assert created["report"]["detail"]["差异键数"] == 3

    # 重新读取（模拟刷新页面 / 重启进程）仍能查到差异键
    loaded = pipeline.get_reconcile_report(created["report"]["id"])
    diff = loaded["diff_list"]
    assert diff is not None
    assert diff["key_count"] == 3
    kinds = {(k["biz_day"], k["store_code"]): k["diff_kind"] for k in diff["keys"]}
    assert "金额漂移" in kinds[("2026-11-10", "S01")]
    assert "仅明细有" in kinds[("2026-11-11", "S02")]
    assert "仅汇总有" in kinds[("2026-11-10", "S99")]

    # 差异键带两侧计数与金额
    s01 = next(k for k in diff["keys"] if k["store_code"] == "S01")
    assert s01["detail_line_count"] == 2
    assert s01["summary_line_count"] == 2
    assert s01["amount_delta"] == pytest.approx(999.0)


def test_recompute_only_touches_list_keys(env):
    seed, pipeline = env
    _full_pipeline(pipeline)
    _corrupt_summary(pipeline)
    created = pipeline.run_reconcile(1)

    untouched_before = pipeline.layer_rows("summary", 1)
    untouched = {
        (r["biz_day"], r["store_code"]): r
        for r in untouched_before
        if r["store_code"] not in ("S01", "S02", "S99")
    }

    result = pipeline.recompute_from_report(created["report"]["id"])
    run = result["run"]
    assert run["status"] == "成功"
    assert run["key_total"] == 3
    assert run["key_success"] == 3
    assert run["diff_list_id"] == created["diff_list"]["id"]

    after = pipeline.layer_rows("summary", 1)
    for r in after:
        key = (r["biz_day"], r["store_code"])
        if key in untouched:
            assert r == untouched[key], "清单外的键不应被改动"

    # 仅明细有的键被补写、仅汇总有的键被删除
    by_key = {(r["biz_day"], r["store_code"]): r for r in after}
    assert ("2026-11-11", "S02") in by_key
    assert ("2026-11-10", "S99") not in by_key
    assert by_key[("2026-11-10", "S01")]["amount_sum"] == pytest.approx(206.5)


def test_recompute_derives_from_detail_not_report_expectation(env):
    seed, pipeline = env
    _full_pipeline(pipeline)
    _corrupt_summary(pipeline)
    created = pipeline.run_reconcile(1)

    # 报告生成后明细又变了（迟到/补录）：重算必须取明细现值，而非报告里的期望值
    from app.db import connect

    conn = connect()
    try:
        conn.execute(
            "UPDATE layer_detail SET amount = 300 WHERE domain_id=1 AND biz_day='2026-11-10' AND store_code='S01' AND category='饮料'"
        )
        conn.commit()
    finally:
        conn.close()

    pipeline.recompute_from_report(created["report"]["id"])
    by_key = {
        (r["biz_day"], r["store_code"]): r for r in pipeline.layer_rows("summary", 1)
    }
    assert by_key[("2026-11-10", "S01")]["amount_sum"] == pytest.approx(386.0)


def test_failed_key_is_isolated(env, monkeypatch):
    seed, pipeline = env
    _full_pipeline(pipeline)
    _corrupt_summary(pipeline)
    created = pipeline.run_reconcile(1)

    original = pipeline._recompute_one_key
    calls = {"n": 0}

    def flaky(domain_id, biz_day, store_code):
        calls["n"] += 1
        if store_code == "S01":
            raise RuntimeError("模拟写汇总失败")
        return original(domain_id, biz_day, store_code)

    monkeypatch.setattr(pipeline, "_recompute_one_key", flaky)
    result = pipeline.recompute_from_report(created["report"]["id"])
    run = result["run"]
    assert run["status"] == "部分失败"
    assert run["key_success"] == 2
    assert run["key_failed"] == 1
    statuses = {it["store_code"]: it["status"] for it in run["items"]}
    assert statuses["S01"] == "失败"
    assert statuses["S02"] == "成功"

    # 已成功的键保持写回，失败键与清单外键保持原样
    by_key = {
        (r["biz_day"], r["store_code"]): r for r in pipeline.layer_rows("summary", 1)
    }
    assert by_key[("2026-11-11", "S02")] is not None
    assert by_key[("2026-11-10", "S01")]["amount_sum"] == pytest.approx(206.5 + 999)


def test_status_and_diff_list_share_source(env):
    seed, pipeline = env
    _full_pipeline(pipeline)
    created = pipeline.run_reconcile(1)
    assert created["report"]["status"] == "一致"
    assert created["report"]["detail"]["差异键数"] == 0

    _corrupt_summary(pipeline)
    current = pipeline.current_reconcile_state(1)
    assert current["status"] == "存在差异"
    assert current["diff_key_count"] == 3

    report = pipeline.run_reconcile(1)
    assert report["report"]["status"] == current["status"]
    assert report["report"]["detail"]["差异键数"] == current["diff_key_count"]


def test_recompute_rejects_report_without_drift(env):
    seed, pipeline = env
    _full_pipeline(pipeline)
    created = pipeline.run_reconcile(1)
    with pytest.raises(ValueError):
        pipeline.recompute_from_report(created["report"]["id"])


def test_swapped_amounts_detected_even_when_totals_match(env):
    seed, pipeline = env
    _full_pipeline(pipeline)
    from app.db import connect

    # 两个键之间挪金额：总额与行数合计都不变，但逐键已漂移
    conn = connect()
    try:
        conn.execute(
            "UPDATE layer_summary SET amount_sum = 55 WHERE domain_id=1 AND biz_day='2026-11-10' AND store_code='S01'"
        )
        conn.execute(
            "UPDATE layer_summary SET amount_sum = 206.5 WHERE domain_id=1 AND biz_day='2026-11-10' AND store_code='S02'"
        )
        conn.commit()
    finally:
        conn.close()

    created = pipeline.run_reconcile(1)
    assert created["report"]["detail"]["金额漂移"] == 0
    assert created["report"]["detail"]["明细行数"] == created["report"]["detail"]["汇总行数合计"]
    # 总额看不出问题，但状态仍须为「存在差异」
    assert created["report"]["status"] == "存在差异"
    assert {k["store_code"] for k in created["diff_list"]["keys"]} == {"S01", "S02"}


def test_key_misalignment_with_same_count_and_amount(env):
    seed, pipeline = env
    _full_pipeline(pipeline)
    from app.db import connect

    # 删掉 S01/11-11，再补一个明细里没有的 S77；行数与金额合计都恰好相同
    conn = connect()
    try:
        row = conn.execute(
            "SELECT amount_sum, qty_sum, line_count FROM layer_summary WHERE domain_id=1 AND biz_day='2026-11-11' AND store_code='S01'"
        ).fetchone()
        conn.execute(
            "DELETE FROM layer_summary WHERE domain_id=1 AND biz_day='2026-11-11' AND store_code='S01'"
        )
        conn.execute(
            "INSERT INTO layer_summary(domain_id, biz_day, store_code, amount_sum, qty_sum, line_count) VALUES (1,'2026-11-11','S77',?,?,?)",
            (row["amount_sum"], row["qty_sum"], row["line_count"]),
        )
        conn.commit()
    finally:
        conn.close()

    created = pipeline.run_reconcile(1)
    assert created["report"]["detail"]["金额漂移"] == 0
    assert created["report"]["detail"]["键对齐"] is False
    assert created["report"]["status"] == "存在差异"
    kinds = {(k["biz_day"], k["store_code"]): k["diff_kind"] for k in created["diff_list"]["keys"]}
    assert "仅明细有" in kinds[("2026-11-11", "S01")]
    assert "仅汇总有" in kinds[("2026-11-11", "S77")]

    # 按键重算后两边都收敛
    pipeline.recompute_from_report(created["report"]["id"])
    after = {(r["biz_day"], r["store_code"]) for r in pipeline.layer_rows("summary", 1)}
    assert ("2026-11-11", "S01") in after
    assert ("2026-11-11", "S77") not in after
    assert pipeline.current_reconcile_state(1)["status"] == "一致"


def test_proof_materialized_and_read_only_by_report_or_run(env):
    seed, pipeline = env
    _full_pipeline(pipeline)
    _corrupt_summary(pipeline)
    created = pipeline.run_reconcile(1)
    result = pipeline.recompute_from_report(created["report"]["id"])
    run = result["run"]
    proof = result["proof"]

    # 证明字段来自现算：差异键数取清单、重算键数与成败取逐键结果
    assert proof["diff_key_count"] == 3
    assert proof["recomputed_key_count"] == 3
    assert proof["success_key_count"] == 3
    assert proof["failed_key_count"] == 0
    assert proof["out_of_list_key_count"] == 0
    assert proof["complete"] == 1
    assert proof["status"] == "成功"

    # 两条只读下钻路径都必须能重回同一份证明
    by_report = pipeline.list_recompute_proofs(created["report"]["id"])
    assert [p["run_id"] for p in by_report] == [run["id"]]
    by_run = pipeline.get_recompute_proof(run["id"])
    assert by_run["diff_key_count"] == 3
    assert by_run["out_of_list_key_count"] == 0
    assert [(i["biz_day"], i["store_code"]) for i in by_run["items"]] == [
        (k["biz_day"], k["store_code"]) for k in created["diff_list"]["keys"]
    ]

    # 与对账报告详情内嵌的证明同源
    loaded = pipeline.get_reconcile_report(created["report"]["id"])
    assert loaded["proofs"][0]["run_id"] == run["id"]


def test_proof_records_partial_failure(env, monkeypatch):
    seed, pipeline = env
    _full_pipeline(pipeline)
    _corrupt_summary(pipeline)
    created = pipeline.run_reconcile(1)

    original = pipeline._recompute_one_key

    def flaky(domain_id, biz_day, store_code):
        if store_code == "S02":
            raise RuntimeError("模拟写汇总失败")
        return original(domain_id, biz_day, store_code)

    monkeypatch.setattr(pipeline, "_recompute_one_key", flaky)
    result = pipeline.recompute_from_report(created["report"]["id"])
    proof = result["proof"]
    assert proof["status"] == "部分失败"
    assert proof["success_key_count"] == 2
    assert proof["failed_key_count"] == 1
    assert proof["recomputed_key_count"] == 3
    # 失败键也进了清单内逐键记录，未发生越界写回
    assert proof["out_of_list_key_count"] == 0
    assert proof["complete"] == 1


def test_proof_absent_before_recompute(env):
    seed, pipeline = env
    _full_pipeline(pipeline)
    _corrupt_summary(pipeline)
    created = pipeline.run_reconcile(1)
    assert pipeline.list_recompute_proofs(created["report"]["id"]) == []
    with pytest.raises(ValueError):
        pipeline.get_recompute_proof(9999)


def test_recompute_does_not_copy_snapshot_values_back(env):
    """报告快照里的 summary_amount 与 detail_amount 都不能被当作写回来源。"""
    seed, pipeline = env
    _full_pipeline(pipeline)
    _corrupt_summary(pipeline)
    created = pipeline.run_reconcile(1)
    # 篡改差异清单快照中的期望金额，写回必须不受影响
    from app.db import connect

    conn = connect()
    try:
        conn.execute(
            "UPDATE reconcile_diff_keys SET detail_amount=1, summary_amount=2 WHERE list_id=?",
            (created["diff_list"]["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    pipeline.recompute_from_report(created["report"]["id"])
    by_key = {(r["biz_day"], r["store_code"]): r for r in pipeline.layer_rows("summary", 1)}
    assert by_key[("2026-11-10", "S01")]["amount_sum"] == pytest.approx(206.5)
    assert by_key[("2026-11-11", "S02")]["amount_sum"] == pytest.approx(40.0)
