from fastapi import APIRouter

from app.services import pipeline

router = APIRouter(tags=["总览"])


@router.get("/dashboard")
def get_dashboard():
    return pipeline.dashboard()
