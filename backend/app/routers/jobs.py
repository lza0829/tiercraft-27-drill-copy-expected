from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import pipeline

router = APIRouter(tags=["分层任务"])


class JobBody(BaseModel):
    domain_id: int = Field(..., description="主题域编号")


@router.get("/jobs")
def list_jobs(domain_id: int | None = None):
    return pipeline.list_jobs(domain_id)


@router.post("/jobs/paste-to-detail")
def paste_to_detail(body: JobBody):
    try:
        job = pipeline.run_paste_to_detail(body.domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job["step_label"] = "贴源到明细"
    return job


@router.post("/jobs/detail-to-summary")
def detail_to_summary(body: JobBody):
    try:
        job = pipeline.run_detail_to_summary(body.domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job["step_label"] = "明细到汇总"
    return job
