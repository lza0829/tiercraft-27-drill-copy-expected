from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import pipeline

router = APIRouter(tags=["层间对账"])


class ReconcileBody(BaseModel):
    domain_id: int = Field(..., description="主题域编号")


@router.get("/reconcile")
def list_reports(domain_id: int | None = None):
    return pipeline.list_reconcile(domain_id)


@router.get("/reconcile/current")
def current_state(domain_id: int):
    try:
        return pipeline.current_reconcile_state(domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reconcile")
def run_report(body: ReconcileBody):
    try:
        return pipeline.run_reconcile(body.domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/reconcile/{report_id}")
def get_report(report_id: int):
    try:
        return pipeline.get_reconcile_report(report_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reconcile/{report_id}/recompute")
def recompute(report_id: int):
    """按该报告的差异清单逐键重算，与业务日迟到重算入口分开。"""
    try:
        return pipeline.recompute_from_report(report_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
