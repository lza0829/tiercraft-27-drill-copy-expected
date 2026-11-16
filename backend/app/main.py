from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import seed
from app.routers import api

app = FastAPI(title="筑层", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    seed.init_db()


app.include_router(api)


@app.get("/api/health")
def health():
    return {"正常": True, "项目": "筑层"}
