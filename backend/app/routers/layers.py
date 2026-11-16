from fastapi import APIRouter, HTTPException, Query

from app.services import pipeline

router = APIRouter(tags=["分层"])


@router.get("/layers/counts")
def counts(domain_id: int | None = Query(default=None)):
    return pipeline.layer_counts(domain_id)


@router.get("/layers/{layer}")
def list_layer(layer: str, domain_id: int | None = Query(default=None)):
    mapping = {"paste": "paste", "detail": "detail", "summary": "summary",
               "贴源": "paste", "明细": "detail", "汇总": "summary"}
    key = mapping.get(layer)
    if not key:
        raise HTTPException(status_code=400, detail="分层只能是贴源/明细/汇总")
    try:
        return pipeline.layer_rows(key, domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
