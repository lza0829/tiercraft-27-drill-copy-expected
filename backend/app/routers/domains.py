from fastapi import APIRouter, HTTPException

from app.services import pipeline

router = APIRouter(tags=["主题域"])


@router.get("/domains")
def list_domains():
    return pipeline.list_domains()


@router.get("/domains/{domain_id}")
def get_domain(domain_id: int):
    d = pipeline.get_domain(domain_id)
    if not d:
        raise HTTPException(status_code=404, detail="主题域不存在")
    return d
