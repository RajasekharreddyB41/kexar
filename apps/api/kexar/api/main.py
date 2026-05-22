"""
FastAPI app entry point.

Real routes land starting Day 4. For now this exists to verify that
Render can build, install, and serve the backend from a real URL.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kexar.config import settings

app = FastAPI(
    title="Kexar API",
    description="Resilience runtime for production AI agents",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint, useful for human eyeballing in a browser."""
    return {
        "service": "kexar-api",
        "status": "build in progress",
        "demo": "May 28, 2026",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check for Render. Returns 200 when the process is alive."""
    return {"status": "ok"}
