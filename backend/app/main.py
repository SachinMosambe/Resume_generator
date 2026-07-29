from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.generate import router as generate_router
from app.core.config import settings
from app.core.logging import setup_logging

setup_logging()

app = FastAPI(title="Resume Generator", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(generate_router, prefix="/api")


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "resume-generator", "docs": "/docs"}
